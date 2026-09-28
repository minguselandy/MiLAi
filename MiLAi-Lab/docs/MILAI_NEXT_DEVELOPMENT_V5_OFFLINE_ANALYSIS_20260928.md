# v5 V0–V3：旧失败分类、义务链与请求成本

本阶段没有新增真实模型调用，也没有改runtime。旧R1/R2严格分数仍为5/6。
v5新增的是可追溯解释层：R1 BRIEF是明确当前要求失败；R2 field_plan三个点名字段和不预约都满足，
完整记录复述有遗漏，但该例不能独自证明新的runtime消费bug。

## V0 冻结与四种口径

[重新分类清单](../data/manifests/next-development-v5-v4-reinterpretation.json)覆盖全部六脚本、12条旧轨迹、30条公开消息、44个实际生成ID。
50项来源身份已核对，包括原报告/输入/rubric/精简结果、两个执行freeze以及12组trace/result/manifest。
实际provider ID和最终答案与已发表结果一致，旧输入/评分文件与v4报告提交逐字节一致。

| 脚本 | Legacy R1 / R2 | 当前显式要求解释 | 持久与后续范围 | 诊断完整性 |
| --- | --- | --- | --- | --- |
| field_plan | pass / fail | 点名quantity/destination/packing及不预约均满足 | 完整记录正确形成与交付 | R2未再述item；不能改旧fail，也不把诊断自动变新task fail |
| editorial_revision | pass / pass | 链接位置修订和当前三项惯例正确 | 标题/日期保持，新session采用新链接位置 | 不要求固定卡片数或措辞 |
| independent_note | pass / pass | 两事项保存、保持、无业务动作 | 后续明确all details，完整报告两事项 | 不按固定卡数评分 |
| quotation | pass / pass | 解释归属于虚构人物；没有用户自采纳偏好 | 无误持久化，后续报告none known | 忠实引文情境记录不自动等于采纳 |
| temporary | fail / pass | R1漏BRIEF，R2满足 | 两轮无standing规则和后续泄漏 | 当次格式失败不等于持久scope失败 |
| read_only | pass / pass | 部分查询按packing/paperwork，最后显式complete含location | 原记录保持，实际无新写 | 部分答案额外地点只是诊断 |

R2的竞争解释仍保留：一是“current plan”通常可理解为完整复述；二是原rubric对点名三个字段的用户问题增加了额外完整性要求。
此处不把第二解释冒充唯一自然语言真相。未来评分通过显式输入消除该歧义，而不改历史分。

## V1 合同与 V2 链路

[评价合同](MILAI_NEXT_DEVELOPMENT_V5_EVALUATOR_CONTRACT_20260928.md)分四层：current explicit、persistent、later use、diagnostic。
[旧输入义务分解](../data/diagnostics/next-development-v5-offline/legacy-obligations.json)含6case、55个原文有据的人工分项。
R1/R2各55条人工观测分别保存在[r1 observations](../data/diagnostics/next-development-v5-offline/r1-observations.json)和
[r2 observations](../data/diagnostics/next-development-v5-offline/r2-observations.json)。

每个task-failing要求均指向原user可见片段；持久项区分明确长期请求、保持指令和临时/引文/只读的负范围。
例如独立事项最后一问明确要求all details，完整字段可评分；field_plan后问只点三字段，item/booking再述列为diagnostic。
任务分母不以同一内容出现在current与later两层重复计算。保存语义和确认文本分别看，正确确认不能代替真实写入。

冻结HTTP、实际Store与ToolMessage已经离线核对。R1 prefix链为用户要求yes、requires_memory no、最终prefix no。
R2三个点名字段链均为user yes → memory formed yes → delivered yes → answer yes；item诊断链为
request explicitly enumerated no → formed yes → delivered yes → answer no。这两种no不能归为同一种失败。
no-business从实际业务调用/状态读取，不从“我没有预约”自报取证；持久结果也不由程序semantic_completion字段认证。

离线组合器只验证引用/标识与组合人工观测，语义评分仍由Root承担。[工程回执](../data/manifests/next-development-v5-offline-checks-20260928.json)已验收20个独立窄目标（19＋新增时点边界1）、目标Ruff/Mypy、矩阵和package boundary；两份实际CLI输出各55条。
R1显式24/25、持久25/25；R2显式25/25、持久25/25，另有2个diagnostic fail。这些是新增解释分项，不是替代legacy总分。
原161个source/runner/package/lock文件与v4 R2逐字节一致。未改runtime/CI，未构建或运行完整测试。

## V3 请求组件与费用解释

[请求成本清单](../data/manifests/next-development-v5-request-cost-profile.json)覆盖旧v3 B0、v4 R1/R2各22次实际HTTP。
用原锁定本地Qwen tokenizer和真实chat template离线渲染，66个请求的完整输入token数逐个等于provider usage。
无网络下载、Host或embedding调用。response_format约束及其他HTTP参数不改。

| 组件独立token数 | v3 B0 | v4 R1 | v4 R2 |
| --- | ---: | ---: | ---: |
| system base | 2,398 | 2,398 | 2,398 |
| memory boundary text | 0 | 3,564 | 4,598 |
| current task wrapper | 0 | 396 | 396 |
| ordinary memory view | 1,199 | 1,264 | 1,224 |
| authority labels | 356 | 537 | 537 |
| source/event metadata（含工作引用） | 300 | 3,928 | 3,913 |
| tool schemas | 12,716 | 12,716 | 12,716 |
| checkpoint transcript正文 | 689 | 713 | 699 |
| current user原文 | 733 | 733 | 733 |
| template/BPE边界余量 | 493 | 493 | 493 |
| 完整实际输入 | **18,884** | **26,742** | **27,707** |

组件按实际字符串分段独立tokenize，BPE边界不是任意情况下可加；完整template计数才是最终计数。
这些输入量不同于包含输出的历史19,752/27,613/28,571生成总tokens。
R1最大增长来自引用/回执元数据（+3,628），略高于边界说明（+3,564）；R2边界说明（+4,598）最大，其次元数据（+3,613）。
工具schema是总量最大项，但三版本完全相同，不是新增开销来源。

R2每个请求重复完整工具目录、基础/边界说明和工作引用视图。22次Working State都重复同一个current user ref两次，
open_questions全为空，active_refs有16次为空；7份ToolMessage含观察元数据。
实际10次无写入生成仍交付写工具说明与strict CRUD限制。它们仍是可用工具，不通过意图猜测删除其行为合同。
content_sha256由程序校验且不是任何合法任务工具参数，在这些请求中未观察到Host使用它；这不等于可以删全部来源元数据。

唯一离线精简候选只压紧Durable Memory、Working State和tool observation前缀中的JSON分隔空白。
逐对象反序列化相等；全部键、值、原始用户、记录正文、来源标签、工具实际结果、owner/scope及schema保留。
没有去除空状态、引用或提示条款，没有自动语义判断。

| 版本 | 原完整输入 | 候选完整输入 | 节省 |
| --- | ---: | ---: | ---: |
| R1 | 26,742 | 26,411 | 331（1.24%） |
| R2 | 27,707 | 27,376 | 331（1.19%） |

这个小幅结果没有解决40%–45%的整体成本增加。信息值相等也不证明Host行为完全相等。
按原计划§11/15，首轮V5仍运行未修改v4 R2，精简候选仅离线报告，不悄悄部署或混进首轮方法。
V3建议优化顺序与V5首跑不改runtime同时满足：先测量候选，再保留固定方法验证，后续改变须独立冻结。

## 验证边界与过程记录

数据检查只读旧证据。Root组装第一次用`packed`匹配真实记录的`packing details`而停下，改为对应实际字符串后通过；
这属于机械presence证据修正，不是修改模型输出/语义评分。首次查找capacity模块路径不存在，按rg定位现有providers模块。
首份成本分类把旧v3回执前缀整体列为authority，随后按真实JSON边界拆分metadata并重新离线计数；初版留ignored，费用总数未变。
上述过程均零模型，不能计入新效果样本。组合器检查、V4新输入冻结和后续语义运行仍各自验收。

连续账本仍为2,994 / 3,785,491 / 21,237，SHA保持
`e47de5a370b7c6dad581d836a440411055c01c137ec4c589f95389109a4ca668`。
本阶段支持评价口径分离和请求开销定位；不证明新样本稳定，也不重新打开旧v4同题修提示循环。

## V0–V3 Reflection

| 总规划反思项 | 当前结论 |
| --- | --- |
| 1 支持什么 | 旧评分与显式要求可以分离且保持可追溯，实际token增长可以定位到请求组件 |
| 2 反驳什么 | R2 legacy fail自动证明真实消费bug，或空白精简能消除40%开销，均不成立 |
| 3 首断点 | R1在指令采用；R2额外完整性要求首先是评价合同歧义 |
| 4 更简单解释 | 部分字段问答只回答所问字段，不必归因于记忆丢失 |
| 5 更简单方法 | 保留原runtime；人工可见义务＋离线组合，不增Judge/controller |
| 6 复杂度 | 20项必要工程检查、零模型；空白候选仅约1.2%输入节省 |
| 7 过拟合风险 | 旧55分项是已暴露解释；新内容仍共享任务族，不能泛化为独立holdout |
| 8 反例 | legacy fail同时可以是显式要求pass且diagnostic incomplete |
| 9 决定 | Continue到预冻新小样本；首轮保持v4 R2字节语义，条件阶段待实际失败 |
| 10 理由 | 先消除隐藏义务并分离成本来源，再判断真实失败所处层次 |
