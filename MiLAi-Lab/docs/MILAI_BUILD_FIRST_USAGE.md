# Build-first 开发候选

执行范围见[完整计划](MILAI_BUILD_FIRST_DEVELOPMENT_AND_EXPERIMENT_PLAN.md)。当前包A–D已形成可运行候选，五条初轮真实冒烟已结束并暴露语义及反馈问题，定向修复复测已结束，集中开发集预测运行中，Product仍为NO_GO。

## 实现

`methods/edit_maintenance.py`提供一个来源批次的共同编排：当前原文→可选一次提取→普通dense K10定位→一次既有编辑器→实际提交。普通Host和benchmark调用同一实现，配对CLI仍仅用于原配对复现。`maintenance_recipe`可选`single_pass`或`extract_then_edit`；没有配置此字段的历史入口保持原流程。

普通Host继续先捕获用户来源，再按当前请求权限调用维护；实际工具来源分别处理。启用recipe后不再向Host提供另一套save/update工具。编辑提交仍走`FunctionalEditMemory.apply_writer_proposal`、现有版本和事务。结果单列在`maintenance`及`operation_status.semantic_memory`，空提案不表示事实已保存。普通Host现可复用现有`SemanticRetriever`、BGE-m3和编码计账。

编排进度放在同一个Store的执行namespace中，不进入检索事实。已保存提案使用原操作ID恢复提交；未知模型请求保留pending，重开不自动重发。当前权限和来源可见性仍先于恢复。模型传输由调用者提供，方法层不创建客户端。

旧语境使用现有可见近期来源，与当前证据分开交付，不成为本次新事实。只读呈现展开实际`modifies/overrides`关系及其原有条件与断言元数据；未保存的一般规则明确缺失。撤销后的当前状态与历史读取沿用原版本机制，不由程序推导子组频次。

`methods/append_memory.py`提供主比较所需的`Append-only`事实追加对照。它复用共同recipe、普通表示、来源／时间字段、dense检索、Reader及MemoryService，只允许创建事实事项；更正、撤销和计划变化作为新的带来源陈述保存，旧记录保持。旧候选仍交付以识别重复陈述，原文与提取提示的证据地位与其他组相同。现有suite的`arms`可选择`Append-only`，实验配置须同时选择共同`maintenance_recipe`和I2；当前公开首轮配置仍只运行M。脚本响应下验证了两次真实SQLite提交、旧值保持、日期归属及重开不重复写入，尚无Append-only真实模型结果，不以其没有UPDATE判失败。

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

## 本次验证与边界

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
