# Build-first 开发候选

执行范围见[完整计划](MILAI_BUILD_FIRST_DEVELOPMENT_AND_EXPERIMENT_PLAN.md)。当前包A–D已形成可运行候选，五条初轮真实冒烟已结束并暴露语义及反馈问题，定向修复复测已结束，集中开发集预测已闭合、作者评分运行中，Product仍为NO_GO。

## 2026-10-07 04:29 UTC阶段汇总

本节为用户要求的完整阶段提交，快照时间为**2026-10-07 04:29:00 UTC／北京时间12:29:00**。开发代码基线为`830d23a13c14792b2b2bf116cdc25d4712f09c69`，分支`feat/lab-milai-edit-v2-20261005`，发布到[PR #85](https://github.com/minguselandy/MiLAi/pull/85)，保持open、draft、未合并，基础分支仍为PR #84开发分支。完整计划保持进行中，当前有功能候选，但没有最终方法、稳定优势或Product发布结论。

### 开发完成情况与实际版本

| 范围 | 已实现／已提交 | 实际验证边界 |
|---|---|---|
| 共同维护与Host，`43f5ff7`起 | 单轮／一次提取两种recipe，共用定位、I2编辑器、同一MemoryService及实际提交回执；旧语境与当前来源分开 | 普通Host和benchmark已实际调用；语义质量仍存在失败 |
| 读取与恢复，`45596d8`、`dffc232` | 只读关系展开、历史／当前呈现、未知请求不重发；维护提交后刷新当前普通视图 | 五条冒烟及定向复测已运行；业务仅一次预订／一次补标签；自然回答与语义保存仍有错误 |
| 输入与Reader接线，`c120af7` | 紧凑编辑JSON；容量预览计入旧语境和候选；将applicability接到实际benchmark回答输入 | 七份实际超限请求离线均可容纳；73份保存的Reader请求加入新视图后均可容纳，最大28,721／32,256 tokens。尚无修复版真实效果，当前dffc实验未采用这些改动 |
| 事实追加对照，`66fae63`、`830d23a` | Append-only共用事实提取、dense定位、来源／时间及Reader；普通Host也可选择，修订作为新陈述追加 | SQLite保存、更正旧值保持、来源时间、重开及只读检查通过；真实模型比较与Host效果均未运行 |
| 分阶段运行，`107df58`、`74255b2` | HaluMem、LongMemEval及外部CLI的predict／score分离；结果汇总读共同检查点、独立评分终态及M对Append-only用户配对 | 已保存预测正在原作者评分；评分不重做Writer、Reader或编码。外部28题尚未运行 |
| 同前态比较，`1c8d9c8` | 原四份实际B0前态分别复制给single_pass与extract_then_edit；相同原文、可用旧状态、编辑器、材料预算与Reader | 实际前态16／20／20／16事项，原序号3／6／7／4；工程检查通过，最多34生成／0Judge，真实调用仍为0 |
| 机制与漂移，`ead06ee` | 原生／漂移读取共同recipe的前后快照、实际来源及回执；完整答案审读识别独立评分终态 | 离线读取实际32会话确认33批次、76提交、7未完成编辑批次；1,056个来源引用均有对应会话与原始时间。真实机制／漂移评分尚未执行 |

上述版本分别记录其职责，不混用CI或效果。当前实验始终使用冻结`dffc232ca4c00fd82801cb15d60003969fea4411`；同前态比较已准备的源码快照为`1c8d9c8`；`830d23a`为当前可继续开发的代码。旧`072af2e`实验与`c86a5ea`／`b1d0bbe`原型协议独立保留。

### 当前实验与成本

固定参数为M、extract_then_edit、I2、全部已有编辑特性、BGE-m3普通dense cosine K10、Qwen3.6-35B-A3B-FP8、thinking=true、temperature=1；上下文65,536、输出预留32,768、余量512、输入上限32,256，来源分批4,096、共同正文预算8,192。没有增加模型部署、第二生成家族或审核Agent。

运行目录为`artifacts/build-first/prefix8-v1/M`。预测进程已exit0；原评分Python进程PID691580／会话56331仍活跃，使用同一冻结源码、配置与产物，尚无`terminal-score.json`。用户本次要求总结提交，没有暂停或重启实验。

| 已曝光开发用户，按原配置顺序 | 维护记录 | 保存预测 | 完整作者评估 |
|---|---:|---:|---:|
| 第一用户 | 8/8 | 8/8 | 8/8 |
| 第二用户 | 8/8 | 8/8 | 5/8，原0–4 |
| 第三用户 | 8/8 | 8/8 | 0/8 |
| 第四用户 | 8/8 | 8/8 | 0/8 |
| 合计 | 32/32 | 32/32，73个完整答案 | 13/32，未形成arm终态 |

预测的33批次中，7次在编辑HTTP之前因容量超限而未提交，另有2次实际空提案。72新建＋4事项编辑共76次确认提交；无操作拒绝，四个独立终态合计72事项／203content／68condition，单事项最多10content。维护记录闭合、提案接受和状态不变均不是语义成功指标。

| 互不重叠的已运行范围 | 确认生成响应 | known tokens | 编码次数／known tokens | 结果边界 |
|---|---:|---:|---:|---|
| 五条初轮冒烟，`1a8079b` | 82 | 550,795 | 38／1,592 | 18消息，17执行COMPLETED／1遗忘后答复VISIBILITY_REVOKED；不是17语义通过 |
| 当前视图刷新定向复测，`dffc232` | 18 | 160,508 | 14／710 | 4消息，1COMPLETED／3FAILED，原失败保留 |
| 四用户前8预测，`dffc232` | 132 | 1,566,037 | 198／15,268 | 33抽取386,243＋26编辑663,995＋73Reader515,799；全stop，Judge0 |
| 同一预测的事后作者评分，截至快照 | 285 | 1,053,312 | 0／0 | 全stop；另1请求在途，费用随运行继续增加 |
| 本表范围合计，截至快照 | 517 | 3,330,652 | 250／17,570 | 另1生成在途；不含旧072或更早实验 |

首次`45596d8`冒烟在客户端配置阶段失败，生成／编码均0，失败产物保留。上述两个已闭合冒烟与预测阶段各自新增unknown均0。当前前8目录合计418生成请求／417响应、2,619,349 known tokens；与预测前账本41,140请求／158,573,083 known的差额一致。快照全局账本为41,558请求／161,192,432 known／161,380,513 charged；编码1,120,458 known，原预算不变。当前generation unknown=5包含历史4和1次在途预留，不能把在途当作新增已闭合未知失败。第一用户的159次Judge／750,478 tokens已包含在285次中，不重复相加。

### 已获得的语义证据

第一用户8会话的原作者更新Correct为**4/19（valid19）**，QA为**15/20（valid20）**；形成参考点122中valid判断116，17个形成输出中valid判断14，无效判断保留。其原3／4／7的容量失败覆盖12个更新机会，作者标为11个Omission、1个Correct；原6的真实空提案仍有1个Correct和2个Omission。这说明容量失败确实影响任务，也说明Correct标签不必然证明本次发生持久修订。没有发布其余用户或整个M组的终态分数，不与旧版本B0/B1排名。

Root已复核第一用户20个完整自然答案，并对第二用户原3／4／5的重点来源、提案及前后状态做了开发复核，读过原5的3个完整答案；没有另造数值重评分，也不称独立评审。第二用户原3四个作者更新标签均Correct，但实际精确金额来自Assistant、编辑却绑定为用户自述，且季节波动／储蓄淡季用途从当前条款消失；这些来源与非目标保持问题继续单列。原4健康分类也有相同归属问题。原5追加带日期偏好后Reader能够协调新旧时间，不单凭没有UPDATE判失败。

初轮Host还存在限定强化、整体频次无依据推广到子组、旧否定事项漏改、部分业务效果误写、遗忘后误称从未保存等问题。视图刷新修复已实际交付新状态，但复测仍有编辑截断和耗尽读取额度，不能把实现修复写成完整功能通过。所有问题集中在[问题表](MILAI_BUILD_FIRST_ISSUES.md)。容量整理是已准备的主要工程修复；单轮与两阶段的净收益仍待真实比较决定。

### 检查、发布与剩余任务

检查按改动范围执行，不把重叠测试数量累计为功能成绩：同前态入口27项受影响检查、机制诊断18项、最新Host适配器84项及6项Host定向集成检查通过；相应Ruff、mypy及包／工具依赖边界检查通过。传输脚本与SQLite检查仅证明工程行为。冻结实验源码dffc232自身[Fast](https://github.com/minguselandy/MiLAi/actions/runs/37563832351)／[Full](https://github.com/minguselandy/MiLAi/actions/runs/37563832443)均success；比较入口1c8d9c8自身[Fast](https://github.com/minguselandy/MiLAi/actions/runs/37569826020)成功、[Full](https://github.com/minguselandy/MiLAi/actions/runs/37569826077)查询时运行中；诊断ead06ee自身[Fast](https://github.com/minguselandy/MiLAi/actions/runs/37570083654)成功、[Full](https://github.com/minguselandy/MiLAi/actions/runs/37570083728)运行中。当前代码830d23a的[Fast](https://github.com/minguselandy/MiLAi/actions/runs/37571246042)／[Full](https://github.com/minguselandy/MiLAi/actions/runs/37571246043)均查询时运行中；本次报告提交有自己的CI，不能借用这些结果。

| 完整计划要求 | 当前证据与剩余工作 |
|---|---|
| 共同功能候选与第一轮错误定位 | 包A–D工程路径、五条初轮冒烟及集中预测已执行；作者评分运行中，语义缺口保留 |
| 同前态recipe与五组主比较 | 单轮／两阶段入口及B0/B1/B2/M／Append-only均已接通；真实同前态及同版五组比较未开始 |
| 65／277长历史 | 预选首用户65会话／142更新／164QA，以及四用户277／595／705范围保留；须在选定共同版本上各自从空库形成，连续运行的中间观察点不重复计费 |
| 原生、漂移、必要消融和预算敏感性 | 原32机会／12会话／4用户、逐次漂移与恢复区分、M入口消融及一个固定较紧预算仍待执行；短前缀不替代完整范围 |
| 保留用户与外部确认 | 16保留用户尚未用于开发，候选冻结后才运行；LongMemEval28题／1,354历史出现、原10题完整答案审读及RawRAG／RollingSummary／A-MEM实际对照尚待本候选验证 |
| 完整Host与新故事 | 原r52五组135案例／192消息已离线复制到`artifacts/milai-edit/e5-inputs/historical-r52-v1`，真实回归未开始；冻结后的实质新故事、遗忘、partial及中断续办仍须覆盖 |
| 最终交付与结论 | 当前事实／断点、共同实现及复现入口已有阶段材料；同版对照、保留／外部结果、完整功能结果和贡献／限制结论尚未齐备，六项交付仍未全部完成 |

旧冻结072结果原样保留：B0维护／评估32/32，原更新27/72（valid64）、QA49/73（valid68）；B1维护27／评估26、无arm及suite终态，原PID3476759已不存在，原因未确认。B2/M未运行，不记零分，未重启或覆盖旧结果。v13.4 Simplify关闭原复杂关系消歧分支，不代表当前局部编辑研究已完成。

本次阶段提交只更新Lab报告和交接记录，代码已在此前提交中发布，不为总结新增模型调用，不暂停原评分，不合并PR。Product API、Schema、权限、Canonical、Archive、workflow及冻结实验配置均未修改；报告回滚基线为`830d23a`。原始正文、gold、HTTP、reasoning、数据库、私有配置与日志保持ignored。仍为一个逻辑MemoryService，记忆文本不能创造业务身份或实际效果，Product保持NO_GO。

## 实现

`methods/edit_maintenance.py`提供一个来源批次的共同编排：当前原文→可选一次提取→普通dense K10定位→一次既有编辑器→实际提交。普通Host、benchmark及配对比较调用同一实现。`maintenance_recipe`可选`single_pass`或`extract_then_edit`；没有配置此字段的历史入口保持原流程。

普通Host继续先捕获用户来源，再按当前请求权限调用维护；实际工具来源分别处理。启用recipe后不再向Host提供另一套save/update工具。编辑提交仍走`FunctionalEditMemory.apply_writer_proposal`、现有版本和事务。结果单列在`maintenance`及`operation_status.semantic_memory`，空提案不表示事实已保存。普通Host现可复用现有`SemanticRetriever`、BGE-m3和编码计账。

编排进度放在同一个Store的执行namespace中，不进入检索事实。已保存提案使用原操作ID恢复提交；未知模型请求保留pending，重开不自动重发。当前权限和来源可见性仍先于恢复。模型传输由调用者提供，方法层不创建客户端。

旧语境使用现有可见近期来源，与当前证据分开交付，不成为本次新事实。只读呈现展开实际`modifies/overrides`关系及其原有条件与断言元数据；未保存的一般规则明确缺失。撤销后的当前状态与历史读取沿用原版本机制，不由程序推导子组频次。

`methods/append_memory.py`提供主比较所需的`Append-only`事实追加对照。它复用共同recipe、普通表示、来源／时间字段、dense检索、Reader及MemoryService，只允许创建事实事项；更正、撤销和计划变化作为新的带来源陈述保存，旧记录保持。旧候选仍交付以识别重复陈述，原文与提取提示的证据地位与其他组相同。现有suite的`arms`可选择`Append-only`，实验配置须同时选择共同`maintenance_recipe`和I2；当前公开首轮配置仍只运行M。脚本响应下验证了两次真实SQLite提交、旧值保持、日期归属及重开不重复写入，尚无Append-only真实模型结果，不以其没有UPDATE判失败。

普通Host也可通过现有`memory_method: "milai_fact_append_v1"`选择该方案，同时使用`edit_interface_version: "I2"`和共同`maintenance_recipe`，其余功能配置沿用。使用新的运行目录；当前公开开发配置仍选M。Host经原功能提交边界追加事实，只读、历史、明确遗忘及业务恢复继续走既有路径；追加方案不提供改写工具。脚本响应和实际SQLite已验证保存后重开不重复写入、更正追加并保留旧陈述及两个原始时间、只读不维护；尚无该Host方案的真实模型效果，不据此选择最终方法。

该适配的现有功能检查及两种recipe的Host定向检查通过，Ruff、受影响mypy及包依赖边界通过。完整Host回归仍待候选定稿；已用现有`prepare_edit_functional_inputs.py`将原r52五组输入复制到`artifacts/milai-edit/e5-inputs/historical-r52-v1`，合计135案例／192消息，未初始化语义记忆或运行模型。正式执行仍使用`run_functional.py prepare --fixture ... --controls ...`与`run`；没有controls文件的组省略该参数。候选固定后的新故事另行执行，不能把旧输入改名为新故事。

## 使用现有入口

在Lab目录使用已有包含LangGraph依赖的Python环境，设置`PYTHONPATH=src`。以下命令会使用配置中的现有本地服务；`message`与benchmark运行会产生真实调用，需保持串行。配置中的本机服务、tokenizer及账本路径按当前环境填写，不创建新服务或预算。

```bash
python tools/run_functional.py prepare \
  --root artifacts/build-first/functional-v2-personal \
  --config configs/milai-build-first-functional-v1.json
python tools/run_functional.py message \
  --root artifacts/build-first/functional-v2-personal \
  --owner development --session daily --message-id save-1 \
  --text '请记住：我的提醒用静音模式。'
python tools/run_functional.py message \
  --root artifacts/build-first/functional-v2-personal \
  --owner development --session daily --message-id query-1 \
  --text '我现在的提醒偏好是什么？这次只查询，不保存。'
```

同一公开消息显式恢复时使用相同owner/session/message-id/text并加`--resume`。新的用户消息使用新的message-id。下面记录初轮五条冒烟的实际结果；入口可运行不代表完整语义成功。

实验配置使用同一方法实现，首轮只选M作为工程候选，不是最终方法选择：

```bash
python tools/run_edit_suite.py \
  configs/milai-build-first-prefix8-v1.json artifacts/build-first/prefix8-v1 \
  --benchmark halumem --phase predict
python tools/run_edit_suite.py \
  configs/milai-build-first-prefix8-v1.json artifacts/build-first/prefix8-v1 \
  --benchmark halumem --phase score
```

正式首轮在五条冒烟后启动。`predict`保存维护结果、完整答案、逐会话实际状态和作者更新评分所需的原标准检索诊断，诊断在Writer／Reader之后运行并继续计账，不作为维护输入。`score`只复用这些产物执行原作者评分，不重跑Writer、Reader或检索；`all`保留一次运行入口。LongMemEval同样支持预测／评分分开；原无效标签与总机会分母不变。新候选使用新的产物目录，不接写旧冻结运行。B0/B1/B2/M及Append-only主比较、65/277、16保留用户、外部子集和普通Host完整回归均仍在完整任务范围内。

五条冒烟使用一个已公开的功能配置和一个顺序fixture，复用两条既有保存／更正故事、原部分业务故事及实际服务恢复控制，加上一般规则／例外和遗忘消息。每条消息由原CLI重开进程，不用理想卡初始化：

```bash
python tools/run_functional.py prepare \
  --root artifacts/build-first/functional-v2-five-flows \
  --config configs/milai-build-first-functional-v1.json \
  --fixture data/fixtures/milai-build-first-smoke-v1.json \
  --controls data/diagnostics/milai-build-first-smoke-v1-controls.json
python tools/run_functional.py run --root artifacts/build-first/functional-v2-five-flows
```

外部对照沿用`tools/run_edit_external.py --config ... --output ...`，现在也接受`--phase predict|score|all`，并可选择B0/B1/B2/M／Append-only及已有RawRAG、RollingSummary、A-MEM适配。两阶段使用同一冻结配置和产物目录，阶段终态、进度及结束账本分别保存；评分阶段复用已保存的LongMemEval答案，不重做形成、检索或回答。原默认`all`入口保留。已用脚本响应和实际SQLite验证RawRAG预测后重开评分，以及Append-only经外部入口形成状态并调用共同Reader；尚未启动本轮28题真实外部比较，旧外部配置不代表当前候选的冻结配置。

原生机制／漂移及外部完整答案审读入口现在也识别`terminal-score.json`；只有预测终态仍不能当作评分完成。共同recipe的机制诊断复用现有逐批前后快照、实际回执及原始来源，不依赖旧版批次目录；原始时间取来源实际`occurred_at`，历史产物仍沿用其已保存交付时间。未完成批次保留在可用性统计中，不能把无提交当作语义成功。18项受影响检查、Ruff和mypy通过，覆盖两种产物格式、未来来源隔离、独立终态及容量失败；未新增真实Judge调用。

## 同前态recipe比较

现有配对CLI增加`compare`，使用原B0首用户已曝光的原3／6／7／4四份实际前态，记录数16／20／20／16；每种recipe分别复制准备库，使用相同当前原文、B0编辑器、普通dense K10、输入预算及Reader。候选由各自recipe正常检索，不保证两组检索结果相同；不使用理想旧卡或把旧072答案当作当前源码的单轮结果。

```bash
python tools/run_edit_change_pairs.py compare \
  /absolute/path/to/prepared-inputs /absolute/path/to/private-config.json \
  artifacts/build-first/recipe-pairs-v1 --source-version COMMIT
```

`prepared-inputs`为原`prepare`输出，包含`inputs.json`和四份SQLite库；在冻结源码目录运行时使用绝对输入路径。`compare`分别保存实际前后状态、共同维护结果、每个原问题的完整回答及每组成本终态。最多4次单轮编辑、4次抽取、4次两阶段编辑、22次Reader，共34次生成，Judge0；容量失败可能减少调用。没有自动重试，未知传输结果停止执行；输出目录必须是新的，原准备库和旧运行保留。

入口已用脚本响应和实际SQLite验证两组初态相同、真实修改后可读、无关事项保持、准备库未改；这不是模型效果证据。四例仍是已曝光诊断，不是独立确认。当前真实比较调用为0，原作者评分占用串行资源，结束后再运行。原`execute`保留历史配对协议，不能将本次`compare`与其结果混写。

## 五条初轮真实观察

固定源码`1a8079b`、公开功能配置v2，运行目录`artifacts/build-first/functional-v2-five-flows`。18条原定消息各使用独立进程：原顺序队列16个COMPLETED、1个VISIBILITY_REVOKED，另1个后续查询被队列标记NOT_RUN；随后单独执行该新只读消息并COMPLETED，没有重发遗忘或覆盖原队列状态。COMPLETED只说明执行闭合。

| 流程 | 实际观察与限制 |
|---|---|
| 保存／读取／重开 | 相同记录重开可查，只读后记录值不变；回答把“尽量”强化为“严格遵守” |
| 更正／历史／未改内容 | 英寸实际改为厘米，海报限定保持；历史读取工具返回旧版，两次纯查询均不写入 |
| 一般／例外／共同条件／撤销 | 例外、共同条件两天及撤销实际提交，旧版保留；旧否定事项已送达却未改，回答出现子组频次推导；共同条件提交后Host引用维护前缓存并声称未更新 |
| 纯查询／未知／遗忘 | 未编造雨伞颜色；遗忘后没有重新显示偏好，原答复协议失败而被遮蔽；新的只读消息错误推断从未保存 |
| 部分业务／恢复／反馈 | 实际预订一次，标签服务恢复后先查询再补标签一次；程序回执明确部分业务和记忆未完成；持久语义仍把部分完成概括为操作失败 |

原队列77次生成、528,871 known tokens；后续只读5次、21,924 tokens，合计82次／550,795，编码38次／1,592 tokens，Judge0。与原账本差额一致，新增unknown0，原unknown4保留，预算未重置。用户来源编辑截断与遗忘后答复失败保留，不修写为通过；原始内容、HTTP与数据库均ignored。

`dffc232`只针对已定位的缓存问题：实际维护提交后重新生成本轮普通视图，已发行历史快照保持。脚本响应定向检查、Ruff及受影响mypy通过；同一例外故事前四条的真实复测从新的空库运行，不能替代本初轮失败。复测4条新消息：1条COMPLETED、3条FAILED；新增例外的编辑截断导致未提交，后续查询与条件更新均耗尽读取额度。条件更新实际提交为两天，运行轨迹确认Host已收到新状态，回执如实报告已提交，但没有完整自然答案。18次生成／160,508 tokens、14次编码／710 tokens、Judge0、新增unknown0；不重发截断请求，原NOT_RUN条目与后续独立step输出同时保留。

集中开发集固定dffc232源码：`artifacts/build-first/prefix8-v1/M`，四个既有开发用户各前8，M候选、extract_then_edit、I2、BGE-m3普通dense K10。`predict`已正常结束，32份维护记录及32份预测保存完毕；同一冻结源码的`score`已启动，尚无完整评分。没有启动其他组或使用16保留用户，不能与旧B0/B1排名。主比较、长历史、保留用户、外部验证和完整Host回归仍未完成。

预测阶段共33个来源批次：33抽取、26编辑、73Reader，132次生成全部stop，分别386,243／663,995／515,799 known tokens，合计1,566,037；编码198次／15,268 tokens，Judge0，新增unknown0。账本从41,140请求／158,573,083 known到41,272／160,139,120 known，charged增加量同为1,566,037，原unknown4与限额保持。后续评分费用单独记录，不重复累加。

7次编辑前容量失败均保留incomplete：首用户原3／4／7、第三用户原3／4、第四用户原6／7；没有编辑HTTP或提交，不能算空提案成功。另有2个批次实际返回空提案。72新建、4事项编辑共76次确认提交，没有操作拒绝；四个独立终态合计72事项、203个content单元、68个condition单元，单事项最多10个content单元。这些计数不证明目标完成或非目标保持；实际来源误归属、限定丢失及带日期追加的观察见问题表。

## 初轮检查与历史观察（保留原时点）

以下记录各次实现和观察时点；最新状态以本文件开头的04:29 UTC阶段汇总为准。

受影响工程检查覆盖普通Host两个recipe实际SQLite提交和重开、只读权限、提交后中断恢复、未知抽取请求不自动重发，以及既有四组schema/来源/版本/遗忘路径。传输使用脚本响应，只能证明工程连接，不能证明真实模型效果。新增只读范围／历史、旧语境和两套基准延后评分检查使用脚本响应与实际SQLite，仍不算真实样本。开发配置离线prepare已成功；截至本候选提交准备时，新增真实生成／编码均为0。

父提交`43f5ff7`的Fast在全包mypy发现旧入口的`parse_object`隐式重导出错误，本候选改成显式重导出并通过受影响类型检查。不能借用父提交CI或把脚本响应检查说成效果通过。本候选受影响的三份测试文件通过，另一个LongMemEval延后评分检查通过；改动文件Ruff、受影响源码mypy及包／工具依赖边界通过。

修改仅在Lab；没有修改Product API、Schema、权限、Canonical、Archive或workflow。原始来源、数据库、运行配置与日志保持ignored。本次代码回滚基线为`43f5ff7`，共同编排之前的基线为`c44713e`。

原冻结072队列独立保留：本次核对PID3476759不存在、串行资源锁可取得；B0维护/评估32/32，B1为27/26，B1及suite没有终态，B2/M未启动。原因尚未确认，不能记作完成或将未运行组记零分。没有重启或覆盖旧队列，账本原unknown=4保留。

当前未完事项集中在[问题表](MILAI_BUILD_FIRST_ISSUES.md)。

首次启动记录：`functional-v1-five-flows`使用45596d8，在计账作用域创建前缺失编码客户端的可选配置默认字段，五个首消息均未进入模型；后续消息未运行。生成／编码新增均0，原unknown=4不变。修复域声明并按VLLMConfig展开默认值，使用同一公开配置文件的v2版本及新目录继续，不覆盖失败产物。

候选源码dffc232自身Fast37563832351成功，Full37563832443查询时仍运行；这不证明语义效果。集中预测开始前原账本为41140生成请求／158,573,083 known／158,723,856 charged／unknown4，编码1,105,190；这是两个已闭合冒烟范围之后的边界，不包括在途开发集调用。

运行中诊断补正：检查dffc232实际代码与Reader输入后发现，新applicability投影此前误接在旧维护分支，benchmark回答仍仅使用已有content／revision evidence。普通Host的投影已生效；不能将本轮benchmark说成验证了新视图。开发工作区已移到实际answer路径，传输测试验证字段真正送达，不热改正在运行的源码或答案。

首用户原3／4／7编辑输入分别36,528／38,240／33,042 tokens，超过32,256上限，三次均未调用编辑器且保留incomplete。新补丁仅去除编辑JSON的结构空格，在同一完整payload上变为29,931／31,165／27,209；原文、十候选、schema与预算都保留。旧来源预览也计入真实旧语境和候选提示，预览依旧不发行写权限。受影响Ruff、mypy和既有接口／runner回归通过；未为补丁新开模型调用，实际效果待新的固定候选验证。

完整预测后的只读补充核对：第三用户原3／4的相同完整请求由32,857／33,027降至26,751／26,913，第四用户原6／7由33,173／33,282降至27,457／27,552；七例均在原上限内。已保存的前三用户54个Reader请求对应状态加入新关系视图后均可容纳，前44例最大28,721，第三用户末会话10例最大16,947；这只是离线输入检查，不是新Reader效果。运行中的评分仍用原dffc232预测，不采用这些补丁。

现有汇总入口已适配共同维护Store检查点和独立`terminal-score.json`，并纳入M与Append-only的用户配对比较。汇总只读SQLite，不把预测终态当作评分闭合，也不把容量失败算成空提案；当前实际产物仍显示评分未完成。受影响结果／runner回归、Ruff、mypy及包边界通过，没有因汇总修复重跑模型。dffc232自身Fast／Full现均成功；107df58自身Fast37566914753成功，Full37566914656核对时运行中，后续提交CI单列。
