# v4 F1–F7 工程合同与 F8 回归门槛

状态：**IMPLEMENTATION_CONTRACT_FROZEN; ENGINEERING_ACCEPTED; SEMANTICS_PENDING**。
对应 [原计划](MILAI_NEXT_DEVELOPMENT_PLAN_20260928_v4.0.md)、[执行记录](MILAI_NEXT_DEVELOPMENT_EXECUTION_GOAL_V4_20260928.md)
和 [F0 历史证据](MILAI_NEXT_DEVELOPMENT_V4_F0_BASELINE_20260928.md)。本文件先约束通用接口，
工程证据见 [F8 A 验收](MILAI_NEXT_DEVELOPMENT_V4_ENGINEERING_20260928.md)。正式运行身份仍须发布后 prepare 冻结，
本合同不是效果结果。

## 顺序与归属

唯一 Sol xhigh 修改 Lab source、runner、直接相关 tests、必要配置矩阵/CI；Root 修改 docs/data 和 ignored 评估编排。
先让真实操作审计与默认无纠正可检查，再接最终 wire 角色和临时工作视图，分别添加 world/事项职责，最后接预算路由。
每段保留必要窄检查回执；仅最终受影响入口/包做一次必要构建。不在结果发布时重复无变化的检查。
不新造 D/E 候选名称；当前系统仍是 B0 普通 ReAct，历史 C 是 opt-in 复现，不成为默认流程。

## F1 / F6：执行事实与来源审计

- 程序依据当前 owner/turn 的实际 AI 工具调用和配对 ToolMessage，记录 operation、record_id、tool_call_id、status 和 receipt。
- CREATE/UPDATE/DELETE/no_change/failed/unknown 分开；无调用只能说明没有观察到写入，不能认证用户保存要求满足。
- 不读取最终回答中的 saved/committed 来生成成功，不要求模型再抄 receipt ID，不新增机械证明 Host 调用。
- 默认 correction_entries=0；历史显式 C=1 仍在旧合同内复现。模型 visible ordinary CRUD schema 保持。
- audit 中的 created_from_event_ids/updated_from_event_ids 只表示该操作之前同 owner/turn 实际可见 user/tool 前缀关联。
  工具自身结果是执行证据，单列；不是该次内容的循环 semantic support。
- provenance 由程序推导，绑定真实消息/工具 ID、正文 hash 与 checkpoint 指针；缺失上下文或未知结果如实标未知。
  semantic_support 为 not_inferred，不因此给语义评分加分。
- 优先使用现有 checkpoint/turn trace；不为审计增加数据库、索引、LLM 或新持久事实层。真实 Store 故障继续传播。

## F2：只对实际请求副本标来源

在 JSON-action 历史重序列化之后、最终 HTTP/容量检查之前投影，避免 AI 工具调用重编码覆盖角色标签。
区分 CURRENT_USER_REQUEST、USER_HISTORY、TOOL_OBSERVATION、DURABLE_MEMORY、ASSISTANT_HISTORY、WORKING_HYPOTHESIS。
这些是来源角色，不是程序断言哪段为真。当前 ordinary record 也不等于来源权威。
原 checkpoint、ID、调用参数和工具回执 JSON 不修改；标记可以包围原内容，但不能代替、删去或纠正其值。
用户当前原文保持其用户身份，不作为系统级指令重新注入。真实模板须检查角色/工具链合法且已进入最终请求。

## F3：当前任务和临时引用

Working State 只含 goal、turn_constraints、active_refs、open_questions，可选 last_action/pending_action 引用。
goal/turn_constraints 是当前真实 Human 消息引用，原文字节在 CURRENT TASK 位置每次 ReAct 续接仍可见；
不新增语义约束抽取器，不声称程序已识别所有自然语言约束。
active_refs 只能来自本 owner/turn 实际 READ 或成功 CRUD，候选预交付不冒称模型已采用。
需要正文时解析当前 Store；UPDATE 后自然得到新内容，DELETE/not_found 不能继续被视作有效记录。
每 turn/session 重建，不写 Local State Bank/ordinary Store/checkpoint，不复制长期计划、实时世界或旧助手结论。
新 session 清空临时约束，普通持久记忆继续保留。

## F4 / F5：语义责任保持简单

用短通用合同区分持续偏好/计划/约定与动态外部世界。记忆中的历史观察不替代必要 live 查询；
实际业务结果包括部分成功/未知，不通过重新执行业务修复记忆。模型自行判断何时形成长期信息，程序不自动分类或写入。
v4 实际 ToolNode 返回时只在当前 turn 的临时元数据与 trace 记录 scope、call ID、正文 hash 和
`observation_received_at`，交付在请求副本标签及程序 audit；原 ToolMessage/checkpoint/Store 不改。
这是程序收到结果的时间，不是业务发生时间、当前真值或语义支持。历史/恢复缺少匹配元数据时明确 unknown。
可独立变化事项优先独立维护，普通正文/精确 ID 足够时不新增 ontology/matter schema。
保留 strict CREATE、UPDATE、DELETE、NO_CHANGE、READ；unknown UPDATE 不变 CREATE。
临时 override 不全局 UPDATE；不相关不 DELETE；过期世界描述不意味着抹除历史事件。
不得使用暴露样本名、答案、值、词语或固定格式前缀来改变业务参数、自动分卡或修补输出。

## F7：事前固定的预算路由

初版机械阈值固定 **N=32 个完整候选、B=6000 candidate tokens、普通 query k=10**，不按脚本调整。
候选 token 计量与实际序列化材料对应，byte 只记观测费用，不另设会暗截正文的阈值。
最终完整请求还必须通过原 HostCapacity：65536 context，4096 output，512 safety，包含目录、角色、当前 prefix、历史及工具 catalog。

1. 全部合法候选符合阈值且最终请求能放下，则全部交付；不得先截成 N 条再称 all。
2. 超机械阈值或实际容量，则用完整当前 query 走现有同 scope ordinary retrieval，交付真实返回并重新核算完整请求。
   N/B 只触发 all→query，不是 query 的第二道硬拒绝预算；query 返回超过6000 tokens但最终请求能放下时仍交付。
   candidate_tokens 与最终完整请求 reserved_tokens 分列，避免人为制造 Attention 瓶颈。
3. query 仍放不下且 Attention 未启用，则显式容量拒绝；不静默截断原消息/记录正文，不伪称材料已送达。
4. Attention 默认关闭，独立 U 关闭。显式开关且真实超限才可进入一次只读选择；候选是原 ordinary records 的引用，
   不先抄成另一份持久 State。若将来 F8 D 获准，控制调用按同一账本/容量记费；本阶段只做工程 Mock 覆盖。
   去掉全部候选后完整请求仍超限时，直接容量拒绝，不支付无用 selector 费用。
   每公开消息最多选择一次；只临时保留选中 ID，每次续接从当前 Store 解析正文，处理更新、删除和新增 active refs，
   新 turn 清空。选择缓存不持久化，任意崩溃后的恢复不在本阶段已验证能力内。

记录 full/returned/delivered candidates、实际 token/byte、触发原因、检索与控制费用。所有 selector 费用进入总成本。
机械覆盖条件分支不等于已经观察到真实 retrieval bottleneck；不因存在该分支便运行 F8 D。
若未来发现语义检索遗漏但尚未超容量，须另冻可解释的 F8 D 比较，不事后改本批路由或用 gold 触发选择。

## F8 A 和 B

A 覆盖计划的八项机械要求，并核对真实序列化模板、同 owner/turn 配对、跨 session 清理、UPDATE/DELETE 后 ref、
partial/unknown side effect 不重放、all/query/关闭 Attention 的容量边界。Mock/局部 Store 是工程证据，不计作真实模型样本。

B 只运行六个既有 v3 脚本的当前 B0：field_plan、editorial_revision、independent_note、quotation、temporary、read_only。
用户输入全部沿用 `data/diagnostics/next-development-v3-p2-formation-r1/*-inputs.json` 原字节；原 rubric 的语义要求和分母不改。
旧 rubric 的 B1/C 晋级门槛是 v3 历史条款，不用于 v4；v4 不重跑旧 C 或把六个脚本称新样本。

本阶段晋级要求：A 必须通过；B 必须真实完成 15 回合，5 个新事项形成、1 次修订＋保持、7 次后续使用、
4 条持久正例完整链以及引用/temporary/read-only 边界均通过，当前 BRIEF 也通过，六个完整脚本合计 6/6。
无模型自报 receipt、无 correction/selector 调用；严格区分正常业务/CRUD 所需多轮与额外机械证明调用。
不要求总 tokens 等于旧 B0；所有视图/检索/失败费用照实记录，不能把少形成当作节省。
若失败，定位实际首断点后只做对应通用修复，保留失败，不偷偷放宽晋级标准或跳入新样本。

真实 B 运行前另冻方法提交、原输入/rubric hash、新配置、六项固定顺序、scorer、独立 namespace/store/checkpoint/world 和账本起点。
Root 串行执行；每脚本空初态，每公开消息沿原输入进入新 session。无历史库旁路，无 gold/rubric 输入运行时。

## 后续仍必须完成

A/B 通过后才创建 F8 C 的 8–12 新脚本并冻结方法/输入；必须覆盖计划列出的十类内容和实际业务/持久链。
目前没有创建这些新文本，也未提前消费新样本。B 的工程/暴露回归不能替代新小样本。
真实瓶颈不足则不启动 F8 D；如足够则按同 bank/模型/历史/工具比较并记录全部成本。
F9 按计划四层指标、七项工程说明、方法稳定和研究门槛逐项审计；不足项保持不足，不能只凭工程代码收口。
