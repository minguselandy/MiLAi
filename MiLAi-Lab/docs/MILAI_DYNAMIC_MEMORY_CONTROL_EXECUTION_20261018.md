# 动态记忆控制 v2 执行记录

2026-10-18，完整目标 active。依据 `MILAI_DYNAMIC_MEMORY_CONTROL_DEVELOPMENT_EXPERIMENT_PLAN_20261018_v2.md`。

D1首条真实闭环已验证；完整目标仍 active。当前切片 D1：共享有限动作循环、规则/固定/Laya/生成式策略、正常 Host 的证据交付接线。
USE_VIEW 只打开原 Store 的视图；REFRESH_VIEW 才调用原解释生成器。
本地 Laya 推理从评测脚本提取至 provider；旧脚本继续调用同一实现。基础权重明确作为零样本诊断。

配置：`configs/dynamic-memory-control-d1-v1.json`。沿用原连续账本与现有7860生成/7861嵌入服务。
旧7862端口当前不可达，已在本配置改为实测可用的7860；没有启动服务或恢复旧任务。
运行环境沿用 `artifacts/jev-reader/cuda-env`，以 site.addsitedir 加载原 http-env 的 Host 依赖；未升级依赖。

验证：129 项 Host/记忆集成测试通过；查询视图/旧训练工具局部组 27 passed、3 skipped，
在原 Laya 环境补跑训练/度量组 9 passed（覆盖那 3 项）；8 个触达源码文件 mypy、Ruff、
package/tools 边界通过。各组有重叠，不求和；未声明全仓或远端 CI。

首次真实运行 `artifacts/dynamic-memory-control/d1-laya-v2`（代码61124918）退出，
`save-1` 已完成真实语义提交，但回答阶段失败：操作日志缺原 Trace 的 event 字段。
Laya 前向 0；生成 10,528 tokens、嵌入162 tokens，新增 unknown0。原失败与已保存状态保留。
2a4f83d2 修复原日志合同并增加真实 Trace 回归（6 passed）；新身份 `d1-laya-v3` 再次退出失败：原 HTTP owner 拒绝请求外的本地模型计算记账。
本次生成13,032 tokens、嵌入218 tokens，新增HTTP unknown0；本地加载尝试的时间未留存，
不能记成0或伪造精确费用。没有完成可用的Laya前向回执。
原账本新增窄的 local_compute 串行入口，仍不允许其中预留假HTTP请求；8项相关测试通过。
`d1-laya-v4` 使用正常Host的来源导入加真实查询，真实基础Laya完成6次前向：
SEARCH → READ0 → READ1 → context1 → REFRESH_VIEW → HANDOFF。
原视图实际保存revision1，控制输入6225tokens；加载7.252秒、推理及准备8.331秒（CPU30.111秒）。
Reader随后400：现有7860未启用auto-tool-choice。首响失败保持；生成known4401tokens，
额外13396tokens的失败请求预留仍为unknown，不能因400自行清零；嵌入0。
37b9cf23修复纯Reader交接：完成控制后关闭其读取工具目录，业务/遗忘任务保留原工具。
6项控制回归、相关mypy/Ruff通过。`d1-laya-v5` 从新空库完成完整交接：
基础Laya真实5前向/4318输入tokens，SEARCH→READ1→READ0→context1→HANDOFF；
原Reader回答10月18日A/B均1000元，11月2日A2000/B1000元，与实际两份来源一致。
没有要求显式引用标签，也未输出标签；这是作者核对的开发结果，不是盲评或泛化成绩。
生成5686tokens、嵌入0、unknown增量0；本地加载5.979秒，决策准备及推理4.760秒。
详见 `data/manifests/dynamic-memory-control-d1-results.json`，其路径指向全部原首响与轨迹。

轨迹反思：READ0之后已经交付context1的全部范围，目录仍提供扩展，造成一次无新信息的操作。
现按原始source_ref/revision/区间覆盖移除这种重复可执行项；未用答案或语义充分性裁剪目录。
7项控制测试及相关mypy/Ruff通过；此目录修复后尚未重跑模型，旧v5成绩不改。
`d1-laya-v1` 只有未执行的 prepare，未产生模型调用。
当前仍为单槽，每请求一次显式 Source 枚举；不声称增量发现或动态策略收益。
不执行 SHA/checksum/内容指纹校验，不改历史实验，不推送/合并，不使用子代理。

下一项：首条真实闭环后，六条独立连续历史从空库运行 C0/C1/C2-base，再加入 C3。
随后完成新家族操作标签与 CE/自身轨迹、两槽和变化复用、匹配机制对照、新保留家族及全部声明种子。
D5 可选维护与表示复用按计划的结果条件决定，不用旧选材权重冒充操作训练。
功能可用性、任务/状态结果、完整成本和论文主张分别判断；当前目标尚未完成。


## E0 六历史执行（后续当前状态）

新输入 `data/fixtures/dynamic-memory-control/e0-v1.json`：六个作者构造家族、48来源事件、24问答、5明确操作。
四策略共96问答位置+20明确操作位置。标签/预期/未来步骤不进入Host；作用域与时间均按实际输入。
`tools/run_dynamic_memory_histories.py`只提供配置和事件顺序，算法仍在共享methods和正常Host。
每条消息结束关闭SQLite，后两题换会话；各策略/家族从独立空库开始。
明确请求与来源捕获有区别：普通来源批次保留角色/原文，显式保存/更正/遗忘走既有Host能力。
本轮补上 `incoming_sources` 逐消息入口，复用原capture和回执，不建立第二来源库。

现有7860无法原生auto工具调用；改用已有JSON动作协议，显式schema调用仍使用其原schema。
同时修复空工具目录的JSON最终回答schema。没有新建服务、修改认证或改写工具提交边界。
60项provider/动作/架构测试、3项来源/请求范围检查及相关mypy/Ruff通过。
协议 `data/manifests/dynamic-memory-control-e0-protocol.json` 在查看本轮模型结果前保存。
E0固定4使用共同pool顺序，不冒称dense固定4；主比较的强dense基线仍需补齐。
运行 `artifacts/dynamic-memory-control/e0-v1` 已从1541deec冻结源码启动，PID4179314、exec88910。
冻结源码位于 `artifacts/dynamic-memory-control/frozen-1541deec/MiLAi-Lab`；开发头不替换运行身份。
首次失败保持，不自动重试。当前批次为显式开发，不能据此选保留集或最佳seed。

已观察：fixed审批4题、rules审批4题答案数值/日期/作用域均符合作者来源；完整交付与状态评分仍待完成。
BASE审批q1为SEARCH→HANDOFF，候选已找到但没有READ，Reader因空材料拒答。完整池可回答，所以记为策略漏读，非系统任务成功。
rules审批q2视图把e2（上一轮assistant答案）作为reported支撑；原直接user来源e0/e1当轮未重新交付给刷新器。
同时视图从带生效边界的规则缩成May2结论。此为来源身份/复用适用范围问题；正确最终答案不能掩盖它。
下一版应让显式刷新消费本轮实际打开的必要旧原文，保留来源身份和时间规则；v1冻结结果不改写。

工作树已增加共享操作状态导出和 `train_bounded_laya.py --task memory_operation`。
导出保持训练/推理同一投影，gold默认空；已有策略选择不是标签。操作接受率与Reader成功分开，
保留多合法动作与mask，并按家族聚合。尚未导出正式训练集、补标或运行操作训练。


### 首批退出与剩余位置继续

初次E0协调器4179314已退出（exec88910 exit1），12位置：fixed/rules审批各4个答案正确；
BASE审批q1为漏READ，q2/q3答案正确，q4 Reader达到8192输出上限，`VLLM_CHAT_TRUNCATED`。
q4控制器已完成7次决策与实际刷新，但没有完成答案；该位置新增生成18979tokens、unknown0。
不能把Host的失败状态说明当作任务答案。原driver、首响、视图及费用保留。

新调度 `e0-v1-remaining1`，协调器35395、exec73048；方法运行库仍是1541deec，
调度器独立冻结7e8df793。读取原12个已关闭位置，只执行未开始的位置；实际各臂银行仍位于e0-v1。
长度失败且用量已知时保留失败并继续下一条不同输入；其他执行异常仍先定位。
这是显式审阅后的剩余工作继续，不是重试或覆盖首响。没有改变方法、预算、数据或Reader配置。

操作监督入口0103fb8f已验证（原Laya环境相关11项测试通过）。实际导出
`e0-prefix12-states-v1/unlabelled.jsonl`含67状态/1家族/12方法位置，gold全部为空，
21个Laya状态与当时实际模型输入直接JSON对照一致。导出wall0.128s/CPU0.128s已记原账本一次。
这些仍是功能开发观察，不是24/128个新训练家族，不是训练完成。

开发头34849348修复显式刷新输入：本轮已打开的旧原文也进入刷新器，保留来源角色与时间规则提示；
旧query-structure默认调用不改变。23项相关测试通过；实际效果尚待新版本验证，运行中的v1不改。
完整目标仍包括六历史剩余位置、实际状态/来源评价、CE与自身轨迹、多槽/增量发现、强对照和新保留确认。


审批历史四策略首次位置已全部尝试（16/116）：固定4/4、规则4/4、BASE2/4、生成式3/4，
这里仅计作者核对的最终答案核心数值/日期/范围符合；完整来源绑定、维护状态与复用质量另评。
BASEq1漏READ；BASEq4与生成式q2均为Reader长度失败，用量已知，保持原失败继续不同输入。
只有一个来源家族，不能把16位置当16独立样本，不能据此宣称方法优劣。
协调器现进入项目负责人历史，正常Host的保存、更正及历史读取还在执行。

当前开发提交：1541deec为E0方法冻结；0103fb8f为操作监督入口；34849348为后续刷新器修复；
7e8df793为已审阅失败后的剩余位置调度。全部仅本地，无push/merge；Product API/Schema/权限未改。
Lab Host新增incoming_sources可选参数。当前package/tools边界通过，未运行完整仓库/远端CI。


## 后续当前状态：历史读取与操作数据（2026-10-18）

E0第二调度在98位置退出：rules/reopen_forget/command-2提案被EDIT_SUPPORT_ROUTE_INVALID拒绝，
随后Host报告FUNCTIONAL_REQUIRED_MEMORY_OPERATION_MISSING。实际未提交，新增45371生成tokens、
41嵌入tokens、unknown0。进程35395已消失，exec73048退出1；不是观察超时。
新调度e0-v1-remaining2（PID415031、exec57568）只继续未执行位置，方法仍1541deec、
协调器7e8df793，旧银行和失败保持。最新观察107/116位置，正在执行Laya遗忘请求。

项目负责人实际状态复核：fixed首次保存被拒绝、更正又截断，当前无语义记录；rules和Laya
首次保存成功到revision1，但更正未提交；generative确实更新为revision2，内容为林岚2月3日起任职。
这说明仅核对最终2月1日/2月3日字符串会高估状态成功。历史题须结合实际前态/提交/所读版本；
语义保存、原文保留和正确的新事实回答分别记录，原fixture里的预期不是提交成功的证明。

开发06a5384f增加真实存储版本目录/精确版本READ，复用原MemoryService与证据包，不复制存储。
测试故意经原提交入口保存错误日期9（原文为1），随后更正3；历史读取确实返回存储的9及原文1，
也验证撤销后不能打开该历史。Host原read_goal投影进入控制状态，视图不替代实际历史。
新事件正文现在作为控制器观察提供，并单独记暴露关系；没有READ/USE就不会自动交给Reader。

511b1872澄清Writer：直接事实只需引用来源，派生支持路线的前提不能是目标自身。
未放宽EDIT_SUPPORT_ROUTE_INVALID校验，实际模型效果尚未在新版本验证。
8bb64192让已知来源可直接REFRESH，保持USE无生成，不强制SEARCH→READ→REFRESH固定顺序；
相同输入没有重复刷新对象时不再提供刷新。已撤销视图的标题/控制器正文/摘要也按原可见性更新。
已闭合轨迹发现Laya4次仅有HANDOFF仍前向，开发版改为程序直接交接，明确不算模型充分性判断。
最新35项相关测试、Ruff及5文件mypy通过；先前依赖边界通过，完整仓库/远端CI未运行。

新来源文件operation-families-v1.json包含24训练家族和8开发家族，均为作者构造的来源历史，
与六条E0功能历史分开；只有来源合同与答案预期，尚无操作gold。审阅修正了过时的问题预设、
清单范围和必要/充分条件措辞；充分来源集合不冒充穷尽最小证明。重复/无关/相关变化在家族内
采用六种顺序，且报告时刻按实际阶段递进，避免固定事件计数成为语义变化标签。

收集协议已保存于dynamic-memory-control-operation-collection-protocol.json。
collect_memory_operation_states.py通过相同执行器形成实际来源、缓存视图和反馈；脚本前缀只作
候选示范，不是正确标签。视图必须用实际Qwen首响生成，之后审阅；收集阶段不执行Reader，
不能写成任务成绩。先统计真实可标注状态/长度，再确定普通CE更新数。

串行等待器operation-collection-dispatch-v1.json（PID459851、exec13707）已启动，代码冻结efbdfe9c。
它核对E0具体进程，只有退出且调度完成时启动operation-collection-v1；若E0再次失败则停在
NEEDS_REVIEW，不重启任何已尝试位置。此时尚无收集模型调用或操作训练。
待完成范围仍为E0完整语义/状态/成本评价、真实视图审阅与操作CE、自身轨迹、两槽及增量发现、
强dense基线和机制对照、新保留确认及正常沙箱任务。完整目标active，未推送或合并。


### 已闭合位置的证据与状态审阅

新增只读导出工具summarize_dynamic_memory_histories.py，导出实际回答、最后交付材料、控制路径、
维护回执、实际记录和原账本增量，默认不产生语义评分。首批导出e0-review-prefix108-v1含108位置；
其准备CPU/墙钟已记录但尚未汇入账本，后续收尾一次结算。
人工审阅记录在dynamic-memory-control-e0-partial-review.json，按任务成功而非二元字符串评分：

- 替代支持fixed/q4只读到过期有效资料，漏最新撤回；判断当前仍合格为错。
- rules/q3视图同时保留过期培训有效和导师有效/可领取；Reader却断言无导师支持并拒绝领取。
- rules/q4否定极性碰巧正确，但依据错误的4月3日状态；视图自身也同时保留授权有效与无授权。
- generative/q3未取得OR规则与替代支持便交接，并捏成培训单一路径；q4只复用了其上次错误回答。
- Laya/q3通过实际上下文扩展取得完整原文链，保留导师替代路径。这是一例有效使用共享能力，
  不是模型创新证明；还须补强固定整会话读取基线与dense固定4。
- 遗忘first responses：fixed仅撤销一个record，原始来源撤销0；rules两次未提交；Laya把明确遗忘
  请求解释成无权限。拒答或后来输出旧值要结合这些实际回执，不能直接计为成功遗忘或撤销后绕过。

全部属于作者可见方法的开发审阅，完整96任务/20显式操作评价仍未完成。


## E0关闭与真实操作观察收集关闭

E0所有116位置（96QA+20明确操作）已尝试，remaining2为COMPLETED_WITH_FAILURES，exec57568退出0、
PID415031已消失。未重跑已关闭位置。完整实际材料/回答/提交/成本导出e0-review-all116-v1。
四臂生成tokens分别391940/409619/278141/590670，合计1670370；嵌入3117，新增unknown0。
BASE另有169前向、498117输入tokens，加载29次；实际成本不因少做必要操作而算成净效率提升。
导出准备CPU已单独记原账本一次，未重计模型工作。完整语义/状态评分仍在进行。

操作收集v1在首个视图失败：n2/n3被规则引用但没有定义，原校验拒绝，未保存视图。
实际生成1503tokens、5个决策观察，已计费；子进程506907退出1。等待器退出0只代表调度已结束，
不是子任务成功。原失败完整保留。
02f2ec20补明确节点引用说明，并把已确认的写入前结构拒绝作为操作反馈；保留已有材料，
同一输入不会自动重生视图。缺视图的重复/无关阶段走原文，下一次相关新输入才有新刷新对象。
36项相关检查、Ruff/mypy通过。没有构造缺失节点，也没有放宽校验。

新身份operation-collection-v2已完成：32家族、557状态（train418/dev139）、64次实际Qwen生成，
135342tokens、unknown0。9次视图结构拒绝保留；view_opened计数包含生成后打开和直接复用，
不能当作生成数。exec18927退出0，PID537035已消失。该阶段没有Reader运行、没有gold或模型训练。
结果见dynamic-memory-control-operation-collection-v2-results.json；实际源码冻结02f2ec20。

首批8个生成视图已按原文和引用审阅，记录于dynamic-memory-control-operation-view-review-partial.json：
封签未完成被错误用作允许发运前提；多个图把纯AND写成any=[]（原合同为无路径）；
人员离岗后仍保留当前在岗且错误改引新来源。另有正确保留数量与条件的视图。
这些真实不完美状态保持原样，后续只作有依据的多动作/部分监督或mask，不自动把脚本示范当gold。
完整目标继续active：剩余视图/实际决策标注、普通CE和自身轨迹、两槽/增量发现、强简单与dense对照、
新保留确认及沙箱任务仍待完成。所有提交仍仅本地，无SHA校验、无push/merge。
