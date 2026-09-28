# v5 首轮前瞻结果：持久化正确，旧历史冲突仍失败

状态：R1_COMPLETE / PIVOT_ONE_LAYER；完整 v5 Goal 仍 active，基础方法稳定未达到。
方法为 unchanged v4 R2 `24ef49945cd12eccbd85792fee3c256bf3fe6d2a`，
执行发布提交 `3c207f836ef7f3e35694f4b9cf242846884c3012`（[PR68](https://github.com/minguselandy/MiLAi/pull/68)）。
[协议](MILAI_NEXT_DEVELOPMENT_V5_PROSPECTIVE_PROTOCOL_20260928.md)、
[精简证据/费用](../data/manifests/next-development-v5-prospective-r1-results-20260928.json)与
[133项人工观察](../data/diagnostics/next-development-v5-offline/prospective-r1-observations.json)共同构成结果。
所有10个脚本、27条消息完成；Root核对42个实际生成ID、用户输入、Store/工具、持久化、后续HTTP和回答。
工程链检查10/10不代表任务10/10。

## 冻结门槛与结果

| 分母 | 通过 | 解释 |
| --- | ---: | --- |
| 完整脚本 | 9/10 | assistant_conflict失败 |
| current explicit | 41/41 | 当前显式指令 |
| persistent | 59/59 | 持久字段、更新/删除、负向范围 |
| later use | 29/30 | 当前9被旧历史6覆盖 |
| explicit合并 | 70/71（98.59%） | 高于预冻结95%，但不替代独立类别验收 |
| 内容/实际动作 | 47/48 | 与23/23 no-business义务分列 |
| task-failing总义务 | 129/130 | diagnostic不计入 |
| optional completeness | 0/3 | partial_plan未答未被询问的item/destination/booking；仅诊断 |
| requested持久变化事件 | 11/11 | 8形成请求含15事项，2更新，1删除 |

没有误持久化、虚假保存声明、重复业务动作或隐藏rubric制造的任务失败。
§11合并gate通过；§17/20要求的assistant conflict稳定性失败，因此不能宣布稳定研究底座或完整Goal完成。

| 脚本 | 实际结果 |
| --- | --- |
| complete_plan | 真实CREATE五字段；新session完整回答，未预订 |
| partial_plan | 完整保存；只回答点名的数量和包装，符合任务 |
| one_reply_format | LOCAL:一句解释正确；后会话不延续格式，Store为空 |
| independent_update | 两个事项；同ID把14:10改16:25，日期/房间/钥匙记录不变，后来正确回答 |
| quoted_rule | 一句解释第三方台词，无持久化；后来实际search空结果、没有用户采纳规则 |
| read_only_note | 完整形成；连续两次新会话只读，字段正确、零mutating attempt |
| explicit_delete | 两条独立note；实际DELETE纺织ID，陶瓷ID/正文不变，后来回答CR且纺织已不存 |
| assistant_conflict | 真实6→9同IDUPDATE；回旧session实际交付9且保留旧6，错误回答6 |
| dynamic_world | 真实reserve/label一次，实际lookup得到found/created；原not-booked计划保留，末问正确读旧snapshot |
| moderate_bank | 六条独立note真实形成，两次各回答三个item/location，全部进入请求 |

## 失败的因果链与下一步

**Observed**：H末答“The current saved default sample count for the optics table is 6.”。
**Expected**：当前保存数9。义务来自当前用户显式要求；不要求额外措辞。

链：S1用户6 → 实际CREATE/持久化6 → 真助手答6 → S2真实同IDUPDATE9 → 真助手确认9 →
回S1 HTTP中DURABLE MEMORY为9、原USER HISTORY/旧工具提案/ASSISTANT HISTORY仍为6 →
末条用户明确要求当前durable，即使旧助手不同 → 最后答6，无工具调用或写入。

首断点 **CURRENT_TASK_CONSUMPTION**，表现为当前记忆与保留历史的来源/时间边界未被正确使用。
不是INPUT_MISSING、MEMORY_FORMATION、MEMORY_TARGET或MEMORY_DELIVERY。
“当前存储”只说明该用户当前note，不升级为事实真相或live业务权威。

竞争解释：

1. 当前记忆虽在system中，但请求没有足够明确地区分其当前快照与随后旧会话材料的时间关系。
2. 模型受更靠后的旧6锚定；即使当前用户已明确指定durable，仍发生消费不稳，增长笼统提示未必有效。

旧user、工具提案和assistant均有6，单轨迹不能把因果单独归给assistant角色，也不能证明位置或某条提示必然修复。
同温度一次采样无稳定率估计。其余脚本通过不消除这个独立类别失败。

通用修复候选仅限请求副本中的材料组织或来源/时间契约；不改存储事实、删旧history、按gold补答案，
不加controller/reviewer/selector。Root已将此具体冲突交给匹配Astra xhigh提出局部建议；Sol是唯一实现负责人。
下一实验须先冻结一个候选、旧暴露回归及新冲突/当前约束，保留本轮失败，禁止把本轮内容再称unseen。
没有新增runtime方案被本报告自动接受；最终候选及验收另冻结。
**Continue/Pivot/Stop：PIVOT一个消费/来源边界层；STOP检索架构扩张和措辞扫描。**

## 费用、运行故障与复现

| 生命周期 | generation calls | input | output | generation总tokens | embedding calls/tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| formation | 16 | 24,100 | 1,005 | 25,105 | 15 / 335 |
| maintenance | 7 | 10,447 | 305 | 10,752 | 3 / 37 |
| use | 19 | 23,588 | 594 | 24,182 | 1 / 8 |
| 合计 | 42 | 58,135 | 1,904 | 60,039 | 19 / 380 |

实际memory工具15 CREATE、2 UPDATE、1 DELETE；业务工具1 reserve_and_label、1 get_reservation。
19embedding含两次真实search，费用不剔除。controller/selector/correction/语义重试0。
42次路由均all，最多6条/347candidate tokens，无容量拒绝、HTTP错误或未知usage；Attention **NOT_TRIGGERED**。
新任务内容、工具轨迹和旧v4不同，不能把58,135与旧总量的差解释为压缩或方法开销变化。
原161项runtime/runner/package/lock字节未变；V3空白候选仍未部署。

Store观察：79次memory read/13,528逻辑bytes；30次namespace guard/120bytes；27次checkpoint read/48,945bytes；
operation audit 48,061逻辑bytes，无额外checkpoint read。路由计时含其子步骤，不重复相加。
普通CRUD工具参数字节另列清单，不能充当数据库物理I/O。物理I/O、普通写CPU、GPU小时、货币费用未知。
成功运行进程wall65.058s，HTTP wall22.502s；进程CPU user57.637s/system5.142s，可能因多线程高于wall。

首个运行前置失败也保留：prepare先于Git发布，runner的identity同时绑定git_sha，因而发布后拒绝启动。
已对10job完整重算identity，**唯一差异git_sha**；attempts均空、没有trace/DB/HTTP，账本未变。
保留`prospective-r1/`原10prepare、freeze、失败启动及诊断。必要修复为独立
`prospective-r1-published/`内按已发布HEAD重新prepare/freeze，源码、样本、顺序、工具和参数不变；没有语义重试。
失败启动wall2.302s、user4.660s/system0.414s，所有启动wall67.360s；prepare/Root离线分析时间未单独测量。
该新增身份不一致证据是重新prepare的理由，不是为发布重复已通过检查。
人工观察CLI首次含不允许的额外顶层metadata键而被拒绝；移除该键后133项组合通过，未改判定或runtime。

执行freeze SHA `1ee06b7ff36ebb40ce05e1a8a5de2505e5b0d98eb066f2b2c446963998af8aa3`。
原prepare前freeze SHA `208001c087ef185673f492d882aad4f6e795ee9c07cd8db35c3f5ce572eaddcc`仅关联未进入runtime的启动。
连续账本由2994/3,785,491/21,237增加到 **3036 calls / 3,845,530 generation tokens / 21,617 embedding tokens**，
结束SHA `e7954c9d19b2c35db6cf102abad9f251851c1ba599f23f2c3a985754a36e0339`，历史未清零。

复现固定3c207f83、公开config/inputs/obligations/order；先在该提交prepare，再freeze，并使用全新run/namespace/
checkpoint/业务World，Root串行执行`tools/run_persistent_memory.py run-phase`。私密DSN仅环境注入、原连续账本显式复用。
原结果的工具UUID和非严格确定性推理不是复现gold；不得把生成结果按ID硬编码。

## Reflection

- 本轮成功区分“保存/送达正确”与“当前回答错”；继续修检索会错层。
- 隐藏完整性条件已从任务分移出，而真实H错误仍能被明确可见义务捕获。
- 合并98.59%会掩盖整类冲突失败，必须保留9/10脚本与H独立门槛。
- 当前覆盖真实跨session更新/删除/动态world，但单用户、单模型、小合成bank和一次性短脚本限制外推。
- 一个最小候选必须接受新内容验证及无回归门槛；不能用越来越长system或暴露样本调参宣称稳定。
- Product仍NO-GO、第二家族仍NOT_RUN、整体长程研究目标仍未完成。
