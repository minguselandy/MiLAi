# Contextual user memory v5 合同修复记录

日期：2026-09-24。范围为 [Goal v5](MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v5.0_20260924.md)，仅 Lab 研究原型。状态：`ENGINEERING_COMPLETE_WITH_SEMANTIC_FAILURES`。合同、材料、真实理解修订及 State→Attention→search 接线已有执行证据；最终默认正常完成原始任务、无删除或任务重置，但原生评分 **0／1／0**（latest／contamination／pass），不得称为质量通过。单题 State 功能诊断修复后为1／0／1；唯一H2比较三臂同为1／0／1，没有独立收益。累计114次生成／322283 tokens、embedding22445，失败与局部修复全部计费。以下早期记录按阶段保留；最新验收与剩余语义缺陷见末节。

## 实施与验证顺序

先验证新的空删除无副作用、混合意图整体拒绝、普通路径无删除权限、授权删除与中断续处理；再核对 CREATE／REVISE／NO_CHANGE、受约束条件、日期和公共精简视图。沿用局部提交、准确版本与来源范围，不新增语义审核模型、重试框架或通用事务服务。实现使用 Sol xhigh，文件责任分开；没有下载任务。

合同检查通过后，首先运行新 ordinary 默认配置的 `v11_000977` 自然容量 smoke。普通在线写入诊断固定为 `v11_000977 → v11_000569 → v11_001003 → v11_001002`，只使用已暴露原文、顺序、问题和原生评分。每题至多一份 ordinary 答案；仅预选 `v11_001003` 在新普通快照合法且真实链可核对时附加 RAW 与 H2 各一份，三臂共用公共材料视图、同一合法原文和生成上限。未满足条件则报告未运行，不换题追触发。必要的代码修复后至多一次有记录的局部复核，仍计入原累计预算。

默认上限24次生成／150000 tokens、embedding40000；在线四题全部子阶段共用120次／600000 tokens、embedding250000。不重跑完整 STALE 摄入、不运行全套测试、未使用确认题或其他数据集。配置在对应功能可执行后生成并冻结，阶段保留评分额度，旧账本和运行目录不复用。

已生成[新 ordinary 默认配置](../configs/contextual-memory-v5-default.json)及固定四题在线配置 `contextual-memory-v5-online-v977/v569/v1003/v1002.json`；默认首轮已运行，在线配置尚未运行，JSON、暴露题ID、profile和共用摄入owner已核对。`operation_policy`明确记录维护能力与删除能力缺省关闭，其含义是声明可信runner的固定合同，不是模型可提交的权限开关。只有v1003配置含RAW／ordinary／H2，其他在线题仅ordinary；四题使用同一个外置累计账本及固定上限。

## 旧 STALE 的读取断点（离线，不改旧分数）

只检查未清理的 `v4-stale-ordinary-repair-1` 三份实际答案、问题与工具回执；未读取 gold 来补运行条件，零模型调用。以下对象均在 `1487953e97a23787/` 命名空间。旧对象只作诊断，不声称由新协议自然生成。

| 问题 | 实际取材与答案 | 断点 |
| --- | --- | --- |
| dim1 | 搜索“weekly study time eight hours three sessions”，实际材料为旧八小时来源及 `card:28@1`；随后读取该卡，答案 Yes | 新的短午休状态未出现在本次自然材料，不能说模型已见却忽略 |
| dim2 | 问题含八小时三次的前提；搜索后取到 `card:28@1`，再展开两份旧 assistant 计划，输出3＋2＋3小时安排 | 回答由旧取材支持，未检索到新状态；问题前提与既存旧卡相互强化，不能把前提直接写成新用户事实 |
| dim3 | 第一轮搜索混入运动安排和旧学习建议；第二轮改搜 learning routine／study habits 后同时取到 `card:28@1` 与 `card:57@1`，展开后者，回答工作日午休10—20分钟 | 新状态确实已保存且可取到；同一快照的结果随实际检索与使用不同 |

定位：dim1 答案目录 `85e7a30f…` 的 trace第32／37行；dim2 `04a7ed75…` 第8／13／18行；dim3 `27efe2f9…` 第25／30行。旧原生联合分数仍为0／0／1。两张卡在旧回执中都标为 CURRENT，卡身份不同，不能仅靠当前标记或投影凭空建立它们的语义替代关系。本轮不改检索排序或为此补长历史模型请求。

## 操作合同开发检查

新增不可变 `TaskEnvelope`，由 runner 装配阶段、用户／任务和能力：RAW只读，ordinary可读及维护，query-only无记忆操作。core dispatcher 核对绑定上下文；普通schema不含删除分支。新的空删除直接 `NO_CHANGE`，保存与删除混合先拒绝，普通非空删除先拒绝，均不触发清理或替换任务。可信生命周期入口保留真实删除。

独立删除账本v2冻结操作ID、根／影响引用、用户／任务、受管范围、目的和可保留输入散列，不保存待删正文；删除标记与提交状态跨同一次原子写边界。恢复重放已有标记并完成 pending effects，不重新创建删除操作或增加代次。单一协调入口驱动清理，Host不再根据 `FORGOTTEN` 改写任务。仅删除无需模型；删后续答只用可信保留输入，输入不足明确停止。

第一切片的 ingestion／deletion／Host／runner窄检查41项通过；补齐普通 TaskEnvelope 接线和真实受管清理后，受影响子集38项通过。两批存在重叠，不相加当作总回归。真实清理用例涵盖 trace裁减、progress／checkpoint／chunk删除、SQLite embedding记录及cache-keys清理，随后受控 Host 请求不含被清理正文；中断时保持pending且不续发模型。受影响静态检查通过。S2及S3尚会触及接线，最终身份与对应检查待完成后冻结；当前没有全套测试或模型smoke。

## 写入合同开发检查

普通摄入与回答工具共用判别操作：CREATE不带旧目标，REVISE必须带已交付准确目标和新当前正文，RETAIN_SOURCE只保留已发布来源，NO_CHANGE不产生写入。低层内部save保留兼容，普通模型dispatcher要求明确op。目标版本仍走原CAS，不把错误目标自动换成相似卡；主体／事项语义由Host判断，新正文要求独立可理解，旧正文留在版本历史。

首版可信条件定义只有通用 `setting`：字符串值、外部适用环境、精确匹配；普通提案不能新增定义。未知定义、类型错误及非准确日期在任何来源保留前拒绝，范围说明仍可写入context。省略条件注明未声明结构化范围，不将所有笔记设为PENDING；明确未知时间边界使用uncertain_start／uncertain_end，日期不猜测。旧诊断中非法原值仍保留，不迁成新协议的无条件记忆。

S2及core相关 retrieval／memory／conditions／ingestion／revision／runner切片61项通过，受影响Ruff／mypy通过；其中与前述切片重叠。新增的普通schema单测随后单独通过，最终联合检查尚待Host接线。当前方法身份v8，操作合同v1、写入合同v1、摄入句柄协议v4、材料视图v1；CLI显式记录各自版本，身份相关2项窄测试及静态检查通过。v7 checkpoint不能静默恢复为v8。

## 材料离线对比

[固定读取清单](../data/manifests/contextual-v5-material-offline.json)在计算 tokens 前选定14份既有 read／search 回执，覆盖C首题、v1003、v1002及STALE；清单保存路径、trace散列、调用序号和回执散列，不保存数据正文。所有输入均来自未清理的旧运行，旧smoke已擦除正文未读取或恢复。

相同固定 Qwen tokenizer 下，全部准确正文范围保留的严格口径为78749→22540 tokens，减少71.4%，14包均下降。严格检查按准确对象及字符偏移保持原正文，核对角色、当前状态、适用限制、当前版本引用和必要更正；不同事件不因文字相同合并。同一响应中的相同正文范围只保留一份，关系共用短引用。

默认按需展开口径为19211 tokens，单独报告，不把它与严格压缩混为一个指标：普通出处和前一版可保留展开入口，必要更正和限制不能静默删除。固定清单包含46个独立准确对象／46个准确正文范围，6个旧版行带当前版本引用、11行有明确适用限制或条件、1处必要 `revised_interpretation`；原回执中另1处未展开的必要更正继续明确要求展开，不伪造正文。旧回执的这些统计是出现／准确对象口径，不能当作新方法的真实机制触发率。

投影／delivery／retrieval窄检查12项通过，相关Ruff／mypy通过。完整阶段结果位于 `artifacts/contextual-user-memory/v5-material-offline/result.json`；输入清单、投影实现、离线工具和tokenizer身份随结果固定。这里只证明读取侧合同及压缩，尚未证明新写入质量或在线回答收益；Host和core最终接线仍待整体验证。


## 当前小规模方案与授权衔接

用户本次异步回复“允许修改包C范围，先制定具体小规模方案”，与已记录在 [v4 Goal 第9节](MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v4.0_20260924.md) 的授权相同。旧 C 已执行并冻结，不再启动旧实验或重置费用。本次先交付下列当前 v5 有限方案；本次方案整理没有增加模型请求。

| 步骤 | 固定样本与执行 | 正常生成请求上限（含评分） |
| --- | --- | ---: |
| 默认局部复核 | `v11_000977`，ordinary，自然容量一批；验证已定位回执修复，使用新目录与原默认累计账本 | 1次摄入＋最多8次作答＋1次Judge＝10 |
| 在线首题 | `v11_000977`，6个到达单位，仅ordinary | 6＋6＋1＝13 |
| 在线第二题 | `v11_000569`，7个到达单位，仅ordinary | 7＋6＋1＝14 |
| 唯一候选比较题 | `v11_001003`，6个到达单位；先完成ordinary摄入，真实合法修订链成立才运行RAW／ordinary／H2各一份答案 | 6＋3×6＋3＝27 |
| 在线第四题 | `v11_001002`，6个到达单位，仅ordinary | 6＋6＋1＝13 |

在线全包正常最多67次生成；120次／600000 tokens／embedding250000是包括失败与有明确代码修复依据的局部复核在内的硬上限，不是运行目标。首个在线样本正常最多13次生成，先报告执行链与费用再按预定顺序推进；不因失败换题、扩题或增加候选。默认累计上限仍24次／150000 tokens／embedding40000，已用8次／26212／1828，后续复核共用剩余额度。所有请求并发1，Host／Judge沿用固定Qwen vLLM，开发档位沿用Sol xhigh；本次无下载任务。

到达规则保持已实施的 `online_turn_replay`：每条原始user及其后续assistant为一个单位，按原顺序完整提交后再公布下一个；容量阈值仍6000 source tokens。原文、来源角色、最终问题、评分规则均保留，摄入不能看到未来消息、最终问题或gold。这是在线到达诊断，不把结果当作原生单批收益。

每题先 `--phase ingest` 冻结摄入状态，再检查旧对象提交→新信息和准确目标实际交付→更新提出→合法提交；答题后再核对自然材料及答案使用。只保留来源、另建卡、错误目标修订分别计数，不计作合法修订链。v1003不具备共同有效快照或机制机会时，三臂比较停在摄入，记录未覆盖；不为触发而补旧卡、指定目标或换题。保留已有普通路径失败，不能用H2分数掩盖工程缺口。

## 首个实际默认 smoke 与已定位修复

制品为 `artifacts/contextual-user-memory/v5-default-smoke-1`，自然容量1批，原题 `v11_000977`。历史1次批量提案提交6次RETAIN_SOURCE，保留6个来源、没有创建理解卡；此记录不能当作语义维护成功。回答正常给出轻松家庭观影建议，完成原任务，无删除或任务重置；原生latest=1、旧偏好污染=0、pass=1。Judge使用相同Host权重，评分不证明持久写入可靠。

| 阶段 | 生成请求 | 输入＋输出tokens |
| --- | ---: | ---: |
| 摄入 | 1 | 3323 |
| 作答 | 6 | 21581 |
| 原生Judge | 1 | 1308 |
| 合计 | 8 | 26212 |

Embedding为2次／1828 tokens，unknown usage为0；费用已写入外置默认累计账本。读取材料内部6102→实际投影1571 tokens；写入回执不在该读取分项内，但已计入完整生成费用。历史和答案仍保存在原目录，不复用其不兼容摄入提案。

回答阶段另有一次CREATE：未附来源引用，把整句当前任务叙述填入`setting`，结构上是已定义字符串条件，语义上混入当前问题内容并缺乏合适依据。这违反既有任务说明，作为Host语义失败保留；原生pass不覆盖写入质量，也不以黑名单或按题规则修正它。

实际回执暴露两项确定性缺口：材料行把操作状态SAVED当作版本状态；普通`operation_receipt.operation_id`为空。前者已修复为外层保留SAVED／REUSED、材料依据准确ref/current_ref显示CURRENT／SUPERSEDED或UNKNOWN；受影响材料和Host27项窄检查、Ruff／mypy通过。后者由程序为普通调用分配ID，摄入预先冻结proposal_id并按unit index复用；普通模型参数无法设该身份，生命周期继续使用原账本冻结ID。相关69项窄检查、Ruff／mypy通过，Host在core之前的参数校验、已识别工具参数解析及最终轮save拒绝也已接入程序身份与REJECTED回执；无法识别工具的非法JSON仍为一般解析错误。操作合同升级为v2、摄入协议升级为v5，五份未继续运行的v5配置已同步；旧smoke的配置和源码快照保持原样。

`setting`的answer schema说明也对齐可信定义的环境含义和精确比较，消除与摄入说明的不一致；不改变条件校验规则，不宣称解决Host语义错误。以上具体代码／协议修复是按Goal §8.4安排一次默认局部复核的原因，不因分数或语义失败盲目重跑。

首轮冻结身份：38文件源码映射散列 `d385db7b12399ecbb7416fae4ad75129be1a2a8055ac691b7fcc5f8b030d8169`，配置散列 `bb1f5d9472237292e5e92a8cc73115d9a9342dde27c37650f5e1beb8662ec587`，答案散列 `c5928ab9c39897b92b45ef8f6baaba361471ae18cbef92d794b994992f1585ba`。源码映射及答案散列使用排序键、保留Unicode的JSON序列化口径；不要与文件字节散列混用。

S0—S3接线完成后的联合窄检查为95项通过，覆盖deletion、runner、memory、conditions、ingestion、revision、retrieval、Host、material_view及delivery；受影响11个源文件mypy及Ruff通过，Lab依赖边界检查通过。此批发生在上述回执补丁之前；与前述61、41、38、27、69切片重叠，不能相加。没有运行全套测试、构建、完整STALE或确认集。


回执补丁最终联合检查：`test_contextual_user_memory`、`test_contextual_ingestion`、`test_contextual_deletion`、`test_contextual_runner`、`test_contextual_host_adapter`、`test_contextual_cli_identity`共73项通过，受影响7文件Ruff、operations／core／ingestion／Host四源文件mypy通过。该切片验证成功、无变化与拒绝调用的程序ID、冻结摄入单元恢复身份、Host拒绝接线及配置身份；与前述切片重叠，不额外累加。当前实现为方法v8、操作合同v2、写入合同v1、摄入协议v5、材料视图v1。默认复核及四题在线验证尚未启动，Goal保持进行中。


## 修复后默认复核与在线首题

`v5-default-smoke-2`使用实际交付配置，方法v8／操作v2／摄入v5。1次摄入3466 tokens、6次作答21617、1次Judge1303，合计8次／26386；embedding2次／1828。原题正常回答，native latest=1、contamination=0、pass=1，无删除账本或任务重置。历史仍仅保留6个来源；回答CREATE的操作ID由程序生成、结果COMMITTED／complete，材料行CURRENT，实际验证两项回执修复。`setting`变为“Home movie night setup”，仍未附来源引用；该卡混合历史依据与当前任务表述，保留为语义限制。材料读取6102→1571 tokens，与首轮同口径。默认两轮累计16次／52598、embedding3656，后续不盲目重跑。

`v5-online-v977`先摄入后作答，6批完整覆盖12条原消息，18次操作为12次RETAIN_SOURCE＋6次NO_CHANGE；0理解卡、0修订、无工具失败、无未提交批次。回执的NO_CHANGE无实际变更，不把“committed_units=18”误报为18次记忆变化。首题断点位于创建理解之前，不能证明H2修订链；只运行已规划ordinary原任务，没有候选比较。

该题ordinary正常完成观影建议，native latest=1、contamination=0、pass=1。历史6次／10042、作答6次／24390、Judge1次／1051，合计13次／35483；embedding2次／1828，unknown usage=0。作答1次search＋4次read，无写入，内部读取材料8977→投影2406 tokens。程序及评分执行正常，来源可检索足以回答本题；不能据此声称理解维护已完成。固定下一题仍为v569，推进前只核对source-only是否由schema确定性缺陷造成，不重发本题追触发。

上述两次运行使用相同38文件源码映射 `c63e43b1a0859d62f430a59f29a933484dfc36b315ccb5669536b13201bf5d35`。默认配置散列 `8ac00fb1b6fd65e965d509367548885efb892e8534cd82340c89aad76f7b437f`、历史checkpoint `6a77e6450edc62ffc41ae3a1af87d8cfaf17c91722ee8ff0f869dc4812db0b00`、答案 `fd41a61faf1e062d6d29d361241d70d400c18efd8e2f48e6e2ef2cccab17c1ca`。在线首题配置 `7f33fad55b0a3c2a37ea86ed49c8335981e85f217b63f310a5b3d30e72a1c8a8`、checkpoint `55fc4d3f733ab0233ab1349f045f04d4ddd57d3c3d4255281cabde243f0f3d6d`、答案 `522c27fa712874dd8f596cca8201a036cfd15737501680c35303332828e41a1f`。散列口径与前述JSON一致，旧首轮制品保持冻结。

## 功能实际使用核查与主线调整（零新增模型调用）

用户指出“执行中没有真正使用设计的功能”。本次只读核对 profiles、工具装配、摄入／回答路径，以及在线首题六份实际请求和提案；核查开始时 38 文件源码与上述 `c63e43…` 身份一致。随后工作区另有协议 v6 修改和运行，其身份单独记录。本次功能核查只修改文档，没有改运行代码、配置、数据、旧答案或分数。

| 核对项 | 直接证据 | 可作出的判断 |
| --- | --- | --- |
| CREATE 是否可表达 | 六份请求 schema 均含 CREATE／RETAIN_SOURCE／NO_CHANGE，最小 CREATE 在对应实际 schema 下合法 | 不是工具未提供 CREATE；不据此证明所有可选字段都没有问题 |
| 创建和修订是否发生 | 12 次 RETAIN_SOURCE＋6 次 NO_CHANGE；0 cards、0 history、0 pending；每批 related_record_refs 为空 | 创建处已断开，后续没有旧理解可修订 |
| 历史是否存在维护机会 | 用户先表示重启影评及博客，后表示停止影评并关闭博客；两次表达位于不同到达批 | 有事项变化机会；不能将上游未创建解释成整个历史没有变化 |
| 是否实际使用主动 State | ordinary／ordinary_linked 的 contextual=False，工具表去掉 memory_state；search 构造的主动 attention state 为 None | 此配置没有验证 State 驱动查询和取材；被动条件接线不是主动 State |
| 评分通过依赖哪条可见路径 | 作答只有 1 search＋4 read，无 save | 可见执行是来源检索；不能将 pass=1 归给理解修订 |

六个 `vllm_response` 在该历史 trace 的第 3、16、27、38、49、60 行。核查使用实际发送的 response_format，而非仅看当前函数定义。这里的最小 CREATE 只作离线可表达性检查，没有注入 checkpoint、送入 Host 或成为新 benchmark 样本。

摄入的 `maintenance_settled=true` 表示提案与各局部操作结算完成；当前判定没有证明理解形成或更新。12 次来源保留及6次无变化不能汇总为18次语义记忆修改。也不能只增加一个“至少一次 CREATE”计数器来代替判断：无用卡、错误目标或从问题抄出的卡都不满足要求。

原因分层：CREATE 路径可用但模型未提出是已观察事实；来源保留与理解维护共用一个宽松完成目标，是源码支持的设计缺口；“模型为什么连续选择保留而不形成理解”仍是待验证解释，不能仅凭输出认定模型能力不足或谨慎提示是唯一原因。

下一步按 Goal 第 0 节修正既有维护流程：程序承担授权范围内的确定性来源接收，同一 Host 提案明确处理当前理解；先形成合法旧卡，再验证新来源触发的正确修订。随后到位的四题首轮和协议复核原样保留，不重标成 State 验证。现有 state 能力的真实接线需独立配置身份及有限计划，只能使用原四题和原剩余累计预算；配置未改变前，现有 ordinary JSON 不代表接线完成。v1003 的 RAW／ordinary／H2 单变量比较保持独立。

原生数据、题量、总请求／tokens 上限不变。新增文档核查不计入模型消费；原有失败、费用和通过分数保持原样。合同可靠、功能真实使用和方法独立收益分开验收，后两者不能由当前 smoke 通过替代。


## 四题首轮诊断与一次有依据的协议复核

所有首轮在线运行采用同一38文件源码映射 `c63e43b1a0859d62f430a59f29a933484dfc36b315ccb5669536b13201bf5d35`。固定25个到达单位均完成；共49个独立来源、57次RETAIN_SOURCE和25次显式NO_CHANGE。重复保留的8次调用也正确判为NO_CHANGE，因此实际COMMITTED=49、NO_CHANGE=33，理解卡和历史修订均为0。没有协议拒绝、未提交批次或删除操作。该结果明确不满足真实合法修订验收。

| 原题／目录后缀 | 摄入请求／tokens | 作答请求／tokens | Judge请求／tokens | 合计请求／tokens | embedding tokens | 原生 latest／contamination／pass |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| v977 | 6／10042 | 6／24390 | 1／1051 | 13／35483 | 1828 | 1／0／1 |
| v569 | 7／11835 | 6／25531 | 1／1043 | 14／38409 | 2173 | 0／1／0 |
| v1003 | 6／10370 | 未运行 | 未运行 | 6／10370 | 0 | 无合法修订链，未运行三臂 |
| v1002 | 6／10093 | 4／16361 | 1／1200 | 11／27654 | 1895 | 1／0／1 |

在线累计44次／111916、embedding5896，unknown usage=0；加默认两轮为60次／164514、embedding9552。三份已作答结果全部正常返回和可评分；v569拒绝当前尖锐影评社区请求并使用旧偏好，v977和v1002完成原任务。这是已暴露小样本诊断，不是独立确认集效果。

v569实际材料中，模型在search和最后一次read都完整收到新偏好原文，含“new film discussion group”“old constructive chats”及当前更愿挑错的表达，但最终答案及回答阶段CREATE把顺序倒置。三条read来源在checkpoint的到达序号分别5、3、9；ordinary原始view没有source_sequence／known_at，精简视图省略了event_id，但不能据此把本次错误确定归因于投影：实际正文自身已明确前后变化。CURRENT来源标记表示未被来源替换，不认证为最新用户偏好。本轮不为单题增加排序或额外时序增强。v1002回答及其CREATE采用退出竞赛、转向理论学习的新方向，但仍无历史REVISE，且其setting为笼统说明、无来源引用；不把答案通过升级为语义维护可靠。

零模型只读核对显示，ordinary schema在没有旧卡时保留CREATE／RETAIN_SOURCE／NO_CHANGE，仅移除无合法目标的REVISE；加入真实目标后REVISE正常存在。generation_schema只移除uniqueItems，保留联合分支、必填字段和常量，没有证据支持CREATE被语法约束删除。补充核对确认四题25条历史 vllm_response 的 request 中实际保留 messages 及 response_format，均能检查到 CREATE；在线首题六份实际 schema 的最小 CREATE 离线校验也通过。核查依据包括这些真实请求字段，不只依赖冻结函数定义；这仍不能证明 Host 会正确形成理解。

25批一致退化为仅保留来源，暴露普通历史说明的一项通用缺口：列出了动作，却未明确区分原文保留和当前理解维护这两项决策。按Goal §8.4作一次协议澄清：有足够观察支持可复用事实、偏好、约束或变化时，创建理解或对确实变化的已交付目标修订，并附来源及适当范围；证据不足仍可source-only／NO_CHANGE。不强制每批建卡、不指定题目答案或目标、不改变合法操作集合，也不声称该缺口是失败唯一原因。COMMON_PROMPT、检索、模型和材料预算不改。

只修改ingestion普通分支说明并将协议v5→v6，相关ingestion／CLI identity／runner22项窄检查及Ruff／mypy通过。固定v1003在新目录作一次协议修复摄入，旧source-only结果保留；若仍无合法链，停止本方向，不再改提示追触发。只有真实链成立才继续预选三臂。其余三题不重跑。

新协议影响默认历史摄入，因此最终交付默认配置的answer_calls／Host max_calls从8收紧为6；history holdback请求数按6次作答＋1次Judge同步为7，token预留不变。最后一次默认协议复核正常上限为1＋6＋1＝8，使用原默认累计账本剩余8请求，24／150000／40000上限完全不变。这是新协议修复的回归，不是重复原配置追分数；不足或失败照实保留，不加额。


## 实际生成语法缺陷及已完成的最小修复

通用说明复核目录 `v5-online-v1003-protocol-repair` 六批仍只提出12次RETAIN_SOURCE＋6次NO_CHANGE，0卡／0修订；其中一份assistant来源仅task保留，持久checkpoint为11个来源，12条到达原文覆盖仍完整。新增6次生成／10932 tokens、无embedding，不作答或评分。普通说明不是已证实根因，该失败冻结，停止沿提示方向调整。

协议v6最终默认 `v5-default-smoke-3` 实际为1次摄入3555 tokens、5次作答19974、1次Judge1349，合计7次／24878，embedding1828；原生1／0／1，无删除或任务重置。默认累计23／24次、77476 tokens、embedding5484；在线累计50／120次、122848 tokens、embedding5896。全Goal至此73次／200324、embedding11380，unknown usage=0。曾在进度消息误将默认计为24次，已按账本更正为23次；费用不按上限或预留记实耗。

随后只读实际服务容器中的vLLM 0.27.1及XGrammar 0.2.3实现，发现backend调用compile_json_schema采用默认`any_order=False`，按schema声明的字段顺序生成。ordinary CREATE／REVISE继承`content`在`op`之前；RETAIN_SOURCE／NO_CHANGE没有content字段，因此以op开头的合法序列会在生成时排除CREATE／REVISE。此前静态JSON Schema校验仅证明存在一种合法表示，未覆盖这个有序前缀限制，不能把全部source-only断言为纯语义选择。

零模型、零GPU生成的实际库离线复现位于 `artifacts/contextual-user-memory/v5-grammar-diagnostic/`：`schema.json`、`proposed-schema.json`和`result.json`。原schema接受content-first CREATE，拒绝op-first CREATE／REVISE，却接受op-first RETAIN_SOURCE／NO_CHANGE；统一将op置首后，op-first四种动作均接受。实际31个在线批次提案均以op开头，与该分支限制一致；该证据证明传输合同限制，不单独保证修复后模型会作正确语义决定。

已在共用`ordinary_save_schema`中只调整每个分支的字段顺序，合法字段、required、联合分支及最终校验不变，answer／ingestion一起受益。write contract升为v2、ingestion升为v7，operation保持v2；保留此前通用说明，不再调提示。相关ingestion／Host／runner／CLI46项窄检查、两文件Ruff／mypy通过；实际补丁schema在相同XGrammar中四分支均通过，保存于`fixed-result.json`。未新增运行依赖，未重启服务。

这是一项新复现的确定性缺陷，允许在原在线预算内对预选v1003做一次修复验证；与已失败的说明复核分开归因。其余三题不重跑，旧目录不覆盖。只有真实新合法修订链成立才运行既定RAW／ordinary／H2比较。

### 最终默认回归的有限预算调整提案（已获授权，原提案留档）

修复源码已可审阅，实际默认还需要一份当前源码的完整smoke：v977自然容量，1次摄入＋至多6次作答＋1次Judge，最多8请求。默认原账本仅余1请求。Goal §8.4将分区分别列为上限并禁止自动扩额；子agent核对后认为一般自主审查授权不足以修改这项明示边界。

具体提案：只把默认请求上限24→32、在线请求上限120→112；总请求仍144，两个分区的生成tokens／embedding上限及全Goal总上限均不变。累计已用23与50全部保留，不清零、不借新目录重置。最多执行上述一次8请求默认回归；失败也保留，不继续重试。获授权前保持两个原账本及上限原样，不发起该默认回归；原在线预算中的独立合法验证可继续。


## 日期生成语法修复、真实修订与唯一 H2 比较

op-first 修复后的 `v5-online-v1003-grammar-repair` 已在前四批产生4张理解及2次 REVISE；第五次生成却输出非法 JSON。实际 XGrammar 接受旧日期正则 `^$|^[0-9]{4}-[0-9]{2}-[0-9]{2}$` 对应的错误字符串，同时拒绝合法空值／日期。改为等价分组 `^([0-9]{4}-[0-9]{2}-[0-9]{2})?$` 后，实际库接受空值和准确日期、拒绝错误字符串和 now；日历日期校验不变。离线证据 `v5-grammar-diagnostic/date-result.json`；write v3／ingestion v8，相关条件／摄入／CLI 12项检查及静态检查通过。没有新增模型、服务重启或运行依赖。

失败提案零单元提交，前四批已结算。沿用已有 SHA 固定的 `history_repair`，`v5-online-v1003-date-repair` 原样导入成功前缀，只生成失败批和最后一批；并非 v7 旧记忆迁移，也没有编辑模型输出。前段5次生成12901 tokens（含失败），后段2次5195，实际历史成本7次／18096；embedding 分别1874和574，合计2448。更早两份 source-only 诊断的12次／21302仍在原账本，单独归因。

完整12条原消息按原顺序覆盖，最终6张当前理解、2个旧版本、7个保留来源，pending和错误为0。修订链为 `a14f919cce740239/card:1@1 → @2 → @3`：先离开法律援助志愿工作，后因官僚流程转向直接社区接触，再明确聚焦有结构的高风险青少年课后法律素养项目。两次旧目标在新输入之前真实提交，并以准确已交付句柄修订同一事项；最后一版与真实 user 来源一致。

同时保留语义失败：card:3 把 assistant 自述发表文章误归给用户；两次 REVISE 把前版列为依赖，当前 card:1@3 因依赖旧版显示 NEEDS_REVISION。材料保留这些限制；有合法修订不意味着所有理解可靠。

| 三臂（同一原文；ordinary／H2 同一完整 checkpoint） | 作答请求／tokens | Judge请求／tokens | 原生 latest／contamination／pass | 内部读取→交付材料tokens |
| --- | ---: | ---: | --- | ---: |
| RAW | 3／6590 | 1／1024 | 1／0／1 | 5262→1271 |
| ordinary | 3／9697 | 1／1030 | 1／0／1 | 6555→1582 |
| H2 | 3／9970 | 1／1037 | 1／0／1 | 10653→1723 |

每臂均1次 search、1次 read、无答题写入。H2 search 实际把两份旧来源通过 `revised_interpretation` 关联到 card:1@3，普通臂也已直接检索到相同当前卡；H2 额外关联在响应内合并到既有材料，没有新增独立更正正文。两臂都读当前卡并按结构化青少年项目回答；关系已进入真实材料，但本题没有显示独立质量收益。H2作答生成tokens比ordinary高2.82%，不采用候选，不补题或重跑。

新目录实际14次／34543，embedding2847；加前缀所在目录5次／12901和embedding1874，修复历史及三臂共19次／47444、embedding4721。不能将H2实际embedding零请求（共享cache命中）当作独立成本优势：合并前后历史 trace 的固定tokenizer冷启动唯一输入估计为历史2097，独立RAW2180，ordinary与H2各4370（包含历史与本臂取材）；此估计与实际因重建而重复发生的请求费用分列。仅新目录 summary 中的冷启动数不包含导入前缀，不能直接用来比较完整系统。

冻结源码映射 `c631c80de7b478c2f4132cfce17f648beffe5fce00483d852e1c1ef85a2697ff`；配置 `a61ac724cd1555cdcb9ee3e90bca566b003bb6da1e8e867470ee9e3d2bc4ecfb`；共同 checkpoint `e3f9dfa60390d49485cc9bef58d882241110a6b63b1914ead1471aa3bb712ef2`。三份答案散列 RAW `a1fc0b15f60ee5907cf68eb2943e656bf90f5425ba7f3ff255204a691d0bf584`、ordinary `e7e9efeb521a5df6f42b52c7e2883ce279ad104c620457a19ee5e130e66464ed`、H2 `f6e0750dbaaf1b979b5c434df76043c07f55f3c7be47c61e06a7b80207b9ff99`，口径为排序键Unicode JSON散列。这次运行在新版功能要求重读前已完成，保持原身份，不算 State 验证。

## 新 Goal 接线与固定的最后两项验证

用户明确批准默认32／在线112的请求分区，总144、生成tokens750000、embedding290000不变。修改账本和scope时默认已用23／77476／5484，在线69／170292／10617；总92次／247768、embedding16101，unknown usage=0，全部保留。调整前后快照见 ignored `v5-budgets/authorized-request-repartition.json`。旧运行 manifest 的原分区不改，也不按新配置继续旧目录。

历史摄入 v9 由程序先确定性保留授权原文，再将原有一次 Host 提案用于 CREATE／REVISE／有原因的 NO_CHANGE；来源接收、提案结算和理解变更分别汇总。独立 answer 的 RETAIN_SOURCE 保留。同一 Host 的 state 功能路径先表达非空任务理解，再由下一次 search 消费；普通和 H2 仍 contextual=False。没有第二推理 Agent、额外调用上限、改排序或开启其他候选。

运行前固定[单题功能诊断配置](../configs/contextual-memory-v5-state-v1003.json)：仅 `v11_001003`，现有 `state` profile，plain／full材料，fresh原始6个到达单位；一次历史生成／单位、至多6次答题（包含State和search）、1次原生Judge，总最多13次，使用原online剩余43请求。先冻结摄入检查合法版本链，再核对实际有效查询、主动Attention、选中准确引用、交付范围及限制和答案。无RAW／H2对照，不并入ordinary分数，不宣称State收益；不因语义失败重复生成或换题。

之后只运行一次[当前默认](../configs/contextual-memory-v5-default.json)：v977原题、自然容量、ordinary；最多1＋6＋1＝8次，原default剩余9请求。最终源码自身完成原任务和原生评分才满足默认交付。当前五份普通配置已同步v9，历史修复专用参数已从当前v1003配置移除；历史版本以各自 frozen manifest为准，不授权再做候选比较。

### 功能诊断首轮与局部接线修复

`v5-state-v1003-feature-1` 的v9摄入完成6批、全部12个来源由程序保留；Host产生4次CREATE、2次REVISE、11次带ALREADY_COVERED理由的NO_CHANGE，共17个维护操作结算。card:1@1→@2→@3再次按真实原顺序维护志愿服务事项，两次准确旧目标均在新来源前已提交并在同次提案可见。card:3仍把assistant发表文章误归用户，card:1@2依赖无直接必要性的AI兴趣卡、@3依赖已过时的@2，均保留为Host语义缺陷。

答题首轮失败：3次 `memory_state` 都把自然语言目标放入只接受已交付准确引用的intentions，均在dispatch前以MATERIAL_REF_NOT_DELIVERED拒绝，终态no_progress；未到search、无答案、没有发Judge，不能记原生错误分数。历史6次／15013、embedding2004；失败作答3次／8574，新增总9次／23587。在线累计78／193879、embedding12621，unknown usage=0。

实际首阶段schema仍暴露intentions／conflicts／coverage，但初始化前尚未交付可用引用或search结果，这是阶段接线不完整。具体修复将首State参数限定为context／subject／uncertainty，并要求至少一项非空；准确引用、覆盖判断和后续完整state工具在search后照常使用。可信任务身份及原题明确条件仍由程序建立，不由模型补成持久事实。该修复不改语义答案、样本、模型或6次答题上限。

按§8.4只安排一次此具体修复后的局部复核，至多6次作答＋1次Judge，继续原online累计预算。复用已经完整结算且摄入源码未变的同一历史快照，不重发6次摄入：新运行目录保留原历史身份、原始制品散列和源manifest的显式复用记录，新Host源码另行冻结；历史只算一次实际消费，首轮失败3次不抹除。若同样失败再现，停止本切片，不自动继续试验。


## 最终功能证据与默认回归

State首阶段只暴露context／subject／uncertainty、至少一项非空；search后恢复完整工具。相关Host／core 52项窄检查、Ruff／mypy通过；摄入／runner最终23项窄检查和两源静态检查通过，CLI身份2项通过。上述切片不与早期95／73等重叠结果相加，没有全套测试或构建。最终方法v8、operation v2、write v3、ingestion v9、material view v1。

`v5-state-v1003-feature-repair-1` 使用同一完整历史。初始化State由Host写明“为高风险青少年志愿法律服务选择项目结构，需核对用户偏好、经历和约束”；下一次search的真实effective_query拼接了这份context、subject和uncertainty，state_sha256为 `bedb44adf7041c39ff2a893f580704d44cdbe3e51b055a69110ec9345372eab7`。Attention action=CONTEXT、reason=BASELINE_COVERAGE_UNKNOWN，实际第一条入选准确引用为 `a14f919cce740239/card:1@3`，交付短引用m0及正文范围[0,332]，同时保留UNDECLARED结构范围说明和NEEDS_REVISION旧版依赖限制。Host随后read m0，再展开m13对应的真实user来源，最终回答使用定期工作坊、定制课程和课后法律素养项目。链路由真实State、查询、精确版本、材料、答案相接，不以调用次数代替消费证明。

这份答案5次生成22495 tokens、Judge1次1040，native1／0／1；实际新增embedding2259。读取材料9793→2503 tokens。模型在原工具允许范围内请求limit=10；检索算法和配置上限未修改，且本次无对照，不能解释为State的独立收益。包含首次历史、失败State三次和本次修复，整个功能诊断实际15次／47122、embedding4263。复制的历史trace只计原有一次摄入。历史复用时可选空删除目录不存在，暂存脚本在完成历史复制后停止，未复制embedding cache；执行因此使用全新embedding cache。已逐文件校验完整历史一致并记录暂存经过于 `history-reuse.json`，没有重建、改写或恢复被清理内容，所有实际embedding费用保留。

最终[普通默认配置](../configs/contextual-memory-v5-default.json)在 `v5-default-final-1` 完整执行v977原题。自然容量一批，程序接收12个来源，Host创建4张理解；没有旧对象可作跨批修订，不能把这次自然单批当作在线更新验收。答案5次调用中3次search、1次CREATE和1次最终回答，正常给出舒适、无分析压力的居家观影建议，无State、删除、任务重置或工具错误。历史1次3691、作答5次22312、Judge1次1390，合计7次／27393，embedding2081；读取材料13720→3235 tokens。

该默认原生评分 **latest=0、contamination=1、pass=0**。Judge把可选探索外语片／导演视为分析或学习倾向，并称忽略无生产压力要求；实际答案多处要求放松、避免分析和“应该看”的压力，并将探索限定为仅在有趣、不是负担时。保留这个解释差异，不覆盖原生分数，也不由人工改判通过。答案确实提供原始任务要求的建议，未发生v4空删除导致的任务被改写；因此满足§9的默认执行与冻结要求，质量验证仍为失败，而不是宣称默认通过。

默认历史仍把曾经写博客与后来停写各建为CURRENT卡，说明内容中的历史时态并未建立跨对象修订关系。答题又创建无source_refs的综合偏好卡，混入当前任务及assistant建议；其setting没有可信查询证据，材料正确显示PENDING／UNKNOWN。与v569错误采用旧偏好、v1003角色误归属及不当依赖一起保留为Host语义失败。当前源码不保证可靠的用户事实归属、支持关系或稳定质量，不能用State的单题通过覆盖这些问题。

两个最终运行使用相同38文件源码映射 `c3b1a4dfe1364400a4b6fd8f4ca2963cd5d15f59056239e4de005d87c6a6808c`。State配置 `88295dbc67772c60055f8c789fbc8f251a7b9da87c9e35859cd9c294ddce0f5d`、共同历史checkpoint `8a2943798f3a2b796daa108ae8ed64b32d3f1f030e831a03a2d2c263e30cd674`、答案 `ff3e781339b18fd25d022add53a6f5fe73105f2610383916bb89b5da2d5fc649`；默认配置 `4c576b0156d85c4df930c883e88ac15d25e3c33386b39ecdca4decad5c441ebb`、checkpoint `f03fbcc93c604422c03872a5d55682cd42014b37bb0951f42e3a45215c754f29`、答案 `5ad8b19c879c3735214f029bd755a7ec4cf225621b86297ae356bb7238cc96c2`。JSON散列口径与前文一致；首次失败Host源码及答案继续留在原目录。

## 验收结论与累计费用

| 必需工程交付 | 最终证据／边界 |
| --- | --- |
| 操作与续处理合同 | 五种生命周期情形的窄检查通过，单一协调入口；最后两次真实路径无删除和任务目的变化 |
| 写入合同与真实修订 | 有序语法和日期正则已修；v1003两条真实在线运行都形成同事项@1→@2→@3，准确目标先提交后交付；其他语义失败明确保留 |
| 功能实际使用 | 程序源接收与Host维护分离；修复后的State被下一次search消费，准确当前版本及必要限制进入真实材料和回答 |
| 材料合同 | 固定14份离线材料严格保留准确范围，78749→22540 tokens（−71.4%）；公共状态／限制与响应级去重保留 |
| 当前默认执行 | 最终源码实际完成原题、无未授权副作用；答案和原生失败0／1／0冻结，质量不通过 |
| 唯一H2及方法收益 | 同一快照三臂均通过，H2关联确实交付但普通已取得相同当前正文；无独立收益，H2回答tokens高2.82% |

工程必需交付已完成，Goal按§9关闭为已完成且保留语义失败；关闭不表示普通记忆可靠、默认质量通过或候选获采纳。原生Judge与Host同权重，已暴露小样本及局部修复均不能提供独立泛化结论。H1—H6继续冻结；没有新确认集、完整STALE、全量benchmark、额外候选、Product修改、提交或推送。

| 累计分区 | 实际生成请求／上限 | 生成tokens／上限 | embedding tokens／上限 |
| --- | ---: | ---: | ---: |
| 默认，含全部失败／修复 | 30／32 | 104869／150000 | 7565／40000 |
| 在线四题，含H2、State失败和修复 | 84／112 | 217414／600000 | 14880／250000 |
| 总计 | 114／144 | 322283／750000 | 22445／290000 |

unknown usage全部为0。没有把新目录当预算重置，没有将导入历史再次计为模型消费，也没有为追评分用完剩余额度。费用按实际输入＋输出tokens记账；冷embedding估计与实际请求费用分列。此后没有计划内模型请求。
