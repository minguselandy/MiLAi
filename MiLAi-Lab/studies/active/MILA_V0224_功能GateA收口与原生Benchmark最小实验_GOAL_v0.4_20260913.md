---
goal_id: MILA-V02-24
version: "0.4"
date: "2026-09-13"
kind: FUNCTIONAL_CLOSURE_AND_NATIVE_BENCHMARK_PLAN
document_status: UPDATED_PLAN_NOT_EXECUTION_AUTHORIZATION
gate_a: GATE_A_FUNCTIONAL_PASS_UNDER_R03_R04_USER_PRIORITY
gate_a_work: CLOSED_NO_FURTHER_EFFICIENCY_OPTIMIZATION
next_stage: NATIVE_BENCHMARK_MINIMAL_RUN_SCOPE
native_benchmark_status: NOT_STARTED
old_bcde_route: PAUSED_NOT_DEFAULT_PREREQUISITE
memory_effect_status: NOT_ESTABLISHED
new_model_allocation: 0
new_provider_http_allocation: 0
new_confirmation_allocation: 0
new_experiment_allocation: 0
cumulative_raw_token_cap: null
---

# V0224 v0.4：功能 Gate A 收口，转向原生 benchmark 最小实验

## 1. 目标与本版效力

下一阶段只完成一件事：**在一套已下载的外部 benchmark 原生任务与评价协议下，取得官方简单 baseline 和 MiLAi 普通 Note 的第一批可解释真实模型结果。**

不再以建设通用实验平台、完成整套自建 B–E 矩阵或证明某个 State 机制为默认前置。
先确认任务能原生运行，再接最薄的 Memory 接口；出现重复失败后，才按问题补机制实验。
可用性和功能完成优先，实际成本照实报告，效率不作为新的科学准入门。

本版接替[v0.3规划入口](MILA_V0224_Gate_A至E最新执行与研究_GOAL_v0.3_20260913.md)，不覆盖旧文件或已冻结运行合同。
旧 B–E 前瞻开发与运行按最新收口范围保持暂停；其中有用的校验可复用，但16/16、24/24等大矩阵不自动成为原生benchmark的必经步骤。
未来若需要在旧自建动作世界开展严格Memory因果研究，另列该路线及适用证书，不把原生QA结果直接移作旧Gate E通过。
本轮只更新文档；原证书中的 live 尚需单独合同这一边界不变，新增实验、模型、Provider HTTP和确认配额均为0。

## 2. 已完成的功能 Gate A：到此收口

依据[功能证书](/cra/memory/mx_memory/evidence/v0224/20260913-cpu-completion-segment-v1/functional-gate-a.json)：

| 项目 | 已签发结果 |
| --- | --- |
| Gate状态 | `GATE_A_FUNCTIONAL_PASS_UNDER_R03_R04_USER_PRIORITY` |
| 保证范围 | `COMPOSED_CPU_COMPLETION_WITH_R03_R04_FRESH_SCOPES` |
| 参考与冷执行 | 完整16+80参考；CPU P3 16/16，P4 24/24 |
| 组合边界 | 原P3 16 + 原P4 8 + 新P4 16；40次成功、41次实际尝试，不是单批全成功 |
| 旧失败与成本 | 原第9条超时和旧SQL保留；96次成功路径mock生成 + 4次失败尝试mock生成 =100 |
| 工程检查 | 六项通过，4285测试通过、1项既有可选依赖跳过 |
| 组合验收 | 正确性、隔离、CAS、幂等、回执、世界效果与账务成立，无blocking findings |
| 未证明的事项 | CPU效率门不作为本次通过条件；真实模型请求/实验HTTP均0；尚无Memory效果证据 |

证书SHA256：`3d097412d70592454ae13d27352a03b79f526cd47069dda5f4c688c3c86419a8`。
[工程回执](/cra/memory/mx_memory/evidence/v0224/20260913-a-completion-priority-v1/engineering-v2/engineering-checks.json)与
[一次组合审计](/cra/memory/mx_memory/evidence/v0224/20260913-cpu-completion-segment-v1/independent-composed-k3-completion.json)的摘要与证书绑定一致。
本版仅核对这些已签发文件及绑定，不重新执行其审计、测试或CPU矩阵；工程本机协议HTTP与实验HTTP分账。

按[完成优先修订](MILA_V0224_COMPLETION_PRIORITY_DELTA_20260913.md)和[分段补全修订](MILA_V0224_CPU_COMPLETION_SEGMENT_DELTA_20260913.md)：
不再为18秒、90秒或旧阶段效率阈值做优化；不启用R05、压缩、新缓存或重复校准，不追认旧效率失败为通过。
R03历史静态authority转换、R04同scope去重和跨批组合保证均保留原说明。
该证书认证原CPU测试床，不自动认证新的原生runner、模型、工具或Memory策略。

## 3. 方法调整：使用 benchmark，不先重建 benchmark

默认保留官方任务、历史、时间/事件顺序、工具语义和评分协议。
不再要求首批任务同时满足“自然自写Note + 真冷恢复 + Stable/Changed配对世界 + 动作真值 + Recovery”的完整P链。
原生QA可以先回答记忆取得/使用问题；原生行动任务可以回答任务完成问题，二者按各自证据范围报告。

### 保留与停止

- 保留：权限隔离、合法来源、真实模型输出、真实记忆操作回执、失败与未知用量、官方任务真值和必要的实际输入记录。
- 停止：把每条模型请求变成全研究历史的重新哈希/解析/数据库审计；因小改动反复复制全库、重跑40冷进程或扩展验收框架。
- 不改：A0默认、Product行为、公开部署与Schema NO-GO；Runtime不新增业务推理职责，不直接操作GPU或共享服务。

新原生路线采用明确较窄的**本次运行证据范围**，而不是宣称继承R03/R04的全历史逐边界保证。
本次使用的代码/依赖/数据版本在启动时固定；不可变实验材料不放入每轮重新审计热路径。
权限、当前scope、CAS/操作状态与费用边界仍在必要位置检查；材料或实现实际变更时，记录新版本并重验受影响部分。
旧证书与完整历史留作溯源链接，不自动成为每个新请求的执行依赖。

## 4. N0：只选一个现成入口，做最小运行冻结

沿用[已下载制品与固定revision](MILA_V0218_BENCHMARK_ACQUISITION_20260910.md)，不重新下载全库、不搜索一批新benchmark。
WMA的已有Memory/QA入口可优先核对；ClawMark仅在所需原生服务已经可用时选择；Supersede可作有界更新probe，但不替代行动/冷恢复主张。
具体采用哪一套，以**已有runner最少改造、评价可解释、当前模型与权限能支持**为准，不按“最容易出现State失败”选题。
首轮只选一套，不要求三套同时跑通，也不以MemTrap制品问题阻塞其余路线。

从现有README、入口代码和已知问题记录进行一次简短检查，不再建立新准入平台：

1. 确定可直接启动的官方入口、合法开发子集、一个官方提供的强简单baseline及固定配置。
2. 确认模型/工具/模态与当前HTTP接口相容；不以无实际模型输出的dry-run或Mock冒充跑通。
3. 复用[V0217已知评价风险](MILA_V0217_BENCHMARK_ADMISSION_20260910.md)：排除private-gold回答回退，复核本次实际用到的matcher/checker，不重审全部无关代码。
4. 用少量已知正确、明显错误/否定/缺字段输出核对实际评分路径。涉及动作时核对完整postcondition，不只看一个局部字符串命中。
5. 单列数据许可、当前模型、官方runner/evaluator版本、来源范围、方法差异与所需服务，不记录密钥。

需要Judge才能解释的任务，执行前必须说明Judge是否已有授权、费用与评分方式；本版不新增Judge额度。
没有Judge授权且本地判据不能可靠裁定时，换既定可用入口或明确停在评价阻塞，不临时让被评模型自判。
修改官方reader、模态或evaluator时标 `NATIVE_TASK_LOCAL_ADAPTER/LOCAL_DIAGNOSTIC`，原分与本地诊断分分列，不宣称官方leaderboard复现。

使用一个现有manifest即可冻结：benchmark/code/data/evaluator pin、root与exposure、baseline/模型参数、入口命令、允许工具/服务、用例隔离、资源与停止规则。
若官方协议本身不是冷会话或自主Note，不额外改造它来凑P链，直接缩小结论范围。
本阶段发现环境不齐全时，交付具体缺口或转向另一个已下载的可用入口；不默认为接入一个benchmark重建服务平台。

## 5. N1：先跑官方强简单 baseline，再接 MiLAi 普通 Note

### 小波次与对照

首轮目标为**最多4个独立root，两个主要实验臂**；分为每波2根，最多两波。
root指官方协议的独立任务/trajectory/session群，不把一个root内多个query或阶段算成独立样本。
在任何模型输出之前固定开发候选池、顺序和资格规则，顺序接纳至多4个可运行root；记录拒绝原因，不按gold内容或模型输赢筛选。
已打开任务可以用于本轮诊断，必须标开发暴露；不打开既有保护reserve、candidate57或确认集来补位。

| 臂 | 行为与比较边界 |
| --- | --- |
| `B_native` | 官方现成强简单baseline，保持其正常资料与Memory能力；不人为削弱成必输的无历史Agent |
| `M_note` | 同一任务、模型、工具与资源条件，通过最薄公开适配使用MiLAi普通Note；不引入新的State/关联图/控制器 |
| `R_review`（条件性） | 有值得解释的M_note行为差异时，使用相同Note/当前证据和固定同调用普通review；最多原4根，不扩池 |

第一波先完成B_native的真实轨迹和可评分结果；“跑通”指输入、执行和评价有效，不要求答案全正确。
同一波再完成M_note配对，第二波沿冻结顺序/平衡安排继续。纯接口smoke若与正式配置完全相同且事前已纳入首波，可保留为该位置，不重复付费跑一遍。
这首先是原生任务中的**系统/接线比较**；写入、检索或实际输入不同，不能把差值自动归因于Memory consumption或State机制。

### 最薄适配只做必要映射

- 将官方提供的合法历史/Memory生命周期调用映射到普通公开save/read/search/status；保留原文、时间、顺序和来源对应关系，不凭gold生成摘要。
- 官方要求机械导入时标 `HARNESS_INGESTED`；Agent实际自主保存时才标 `AGENT_AUTHORED`。导入写入不能冒充自选Note。
- 不自行增加mandatory checkpoint、自写正确Note、反事实世界或冷重启要求；若原生协议要求持久化，就用真实公开接口与对应边界。
- Reader只能看到协议允许的内容；答案、gold/evidence标签与评价器私有字段不进在线Host。新接线不继承旧工具的身份写入缺陷。
- Product版本与已公开能力相符，实验隔离；不能为了复用同一Note绕过scope授权、直接复制私表或让一臂读到另一臂的新增产物。
- 记录实际请求里的memory/evidence区块与工具回执；呈现证据不要求重放全研究历史才能成立。

新的真实模型/工具接口只补**本次实际差异**的兼容校验。必要时预留最多2次明确模型兼容探针，未授权即0；零模型负控优先。
不自动重做旧16+24矩阵。小探针不是模型任务能力证明，也不能拿已知正确动作作为原生任务答案提示。

## 6. N2：报告结果，先解释失败，再决定是否研究机制

每条轨迹仅保留必要记录：task/revision、实际输入输出、Memory操作及呈现、工具/环境结果、评分、最早可证实失败层、请求与成本。
完整raw留Git外；manifest、结果表、差异/失败说明留仓库，不新增多层审计数据模型。

归因链：`source available → acquired → presented → interpreted → intent → action encoding → world effect`。
QA任务止于其真实回答/评价链，不强行捏造行动阶段；缺证据标UNKNOWN，不从最终答错倒推Memory错误。

| 观察 | 下一步 |
| --- | --- |
| 官方baseline无法有效运行/评价 | 处理具体官方入口、环境或评价缺口；不开发Memory机制 |
| M_note在接口/取得/覆盖处失败 | 修最小适配问题，保留失败；不解释成记忆固着 |
| 普通Note有效，或与baseline相近 | 报告局部收益/无差异，保持简单 |
| Note与新证据均呈现，且出现重复旧方向错误 | 允许固定R_review条件诊断；不是直接认定Memory因果 |
| R_review解释或修复差异 | `KEEP_SIMPLE`；不把普通复核包装成新State机制 |
| 跨根重复、强简单策略仍不足 | 才提出针对该现象的最小机制试验或受控消费对照 |

首轮报告任务成功/QA正确性、首次相关行动（仅有真实行动时）、重复工作、协议失败、写入/检索/呈现次数和完整成本，分别列指标，不做综合“创新分”。
所有分配、尝试、错误、超时、无写入和未运行均保留；业务结果错不删除配对，系统性隔离/用量失效则停受影响批。
没有自选Note，不计算自主写入持久记忆的固着分母；外部导入/注入只报告对应的记忆消费现象，不冒充自主生命周期证据。
没有实际错误和纠正窗口，不计算Recovery；分母0记N/A。
只有4个root的结果是可行性/开发信号，不是泛化或论文级确认。

## 7. 资源、修订与完成优先

规划包络：主比较最多 `4 roots × 2 arms =8` 个完整原生协议运行单元；条件性review最多再4单元。
每个单元可能包含多会话、多问题、写入或多次工具往返，**12单元不等于12次模型调用**。
具体生成/工具/Judge/辅助HTTP上限由所选官方配置逐项列出，加入所有ingest、失败与最多2次兼容探针，发送前冻结有限总数。
无法给出可执行上限时，选择更小的原生单位，不靠截断任务或隐藏费用制造轻量成绩。

- 累计raw-token硬上限继续为空；模型端点、并发和服务范围明确，不操作GPU或重启共享服务。
- 每请求、worker和阶段保留有限防挂保护；按实际原生协议和合理运行量一次设定，启动、claim、执行与退出层一致。效率统计不转成18/90秒科学门，也不默认照搬旧大矩阵的36小时窗口。
- 真实用量未知立即停止该批发送，禁止自动重试；提交未知先查公开operation/status，不盲目重写。
- 单个用例的可定位问题按最小范围处理；相同未恢复协议错误连续两次停止该用例，避免空耗整轮。共享权限/隔离/账务异常停止受影响批。
- 修复可以复用已打开案例，改实现/提示必须留版本；未受影响结果有据复用，失败不能追认通过或只挑最佳重跑。
- 连续两次修订没有新增可区分证据，停止扩大这条接线，交付具体障碍和替代入口，不再堆缓存/框架。

实际实验费用与策略生命周期费用分开。共用的历史导入或Note形成只在实际账单记一次；摊销次数和未测反事实成本注明，不能假装每臂分别发生或为0。
既有4285测试是Gate A绑定的工程证据，不因写新版Goal而重跑。文档仅校验引用、数字、状态与保留文件摘要；实现改变时先做受影响检查，正式发布/集成再执行所需完整工程验收，不与计时实验争抢资源。

## 8. 后续创新与交付边界

长期方向仍是Host-owned、可错且可修正的认知状态如何调节记忆对行为的影响；人类记忆与ADHD支持方法仅是功能启发。
association、conditional reactivation、stability–plasticity、memory–world consistency与meta-memory保持开放，不预选算法，不新增Runtime语义schema。
在重复失败确实涉及记忆消费后，才按需加入same-input对照、Stable/Changed、真实冷恢复或A→B→A；不要求一个benchmark同时证明所有维度。
候选需面对普通Note、同调用review和适用公开方法；同信息简单方案打平就保留简单。独立确认需另冻未打开lineage、策略、预算与评价，当前不消费C。

本阶段最小交付只有四项：**一个运行manifest、一份薄适配及差异说明、一张逐任务结果/成本表、一份失败归因与研究决定**。
不另造新的benchmark平台或审批框架。

完成条件：所选有界原生批次及应触发对照全部取得终态，输入/评价有效，分母/成本可解释，形成KEEP_SIMPLE、适配问题、局部行为信号或未发现差异的有界结论。
如只有部分运行或环境阻塞，记 `PARTIAL/REVISION_REQUIRED`，不称Memory研究完成；Gate A既有功能PASS不因此被改成失败。

**当前下一步仅是冻结“一套已下载benchmark、最多4根、两个主要臂”的最小真实运行范围。**
本版不启动模型、服务、CPU验收或全仓回归；旧证书、原始失败、旧Goal与暂停的B–E合同全部保留。
