# MiLAi v13.3
## 证据增量维护与正文优先交付
### 失败修复、算法实现与可证伪优势验证规划

版本：v13.3 · 日期：2026-10-02 · 状态：PROPOSED，尚未接入 MiLAi 运行时

基线：PR #79 / `22addcbc378a75d7f854ddc4127eb80f45ca52fb`；main 回滚基线为 `95bf708bfd8aac9f7855485166e3bf739928b949`。[R1]

本次交付为新规划、实现合同、对照实验设计及一个独立的确定性参考内核。没有修改远端仓库、恢复付费模型实验、重写旧数据库或宣称算法优势已经成立。参考内核的 32 项本地测试不属于 MiLAi 真实模型实验，不增加原实验账本。

**总方向保持不变：Grounded Memory + Verified Object References + Semantic/Episodic Memory + Grounded Revision + Lifecycle Recovery。** 一个逻辑 MemoryService；模型做语义选择，程序做真实身份、权限、回执、版本、预算与可验证状态维护。不得以 gold 路由、模糊静默修正、常驻 Reviewer、隐藏业务查询或事后改答制造成功。[R0]

**本版的两个研究算子：**

1. **Evidence-conditioned Delta Maintenance，EDM：**模型只提出有来源的事实增量；未改字段及其支持关系由显式 patch 语义继承，查询不自动成为新事实的依据。
2. **Content-first Evidence Packing，CEP：**在同一材料预算内优先交付完整的事实/正文、范围与版本；完整审计信息留在服务端，通过真实快照句柄关联，不让元数据挤空证据。

确定性工具观察派生、Source 回链、读取时 CAS 和共同边界复用已有实现；不再将其“重新实现”当作新增贡献。EDM、CEP 均为待验证方法，不是通用语义正确性保证。

**执行顺序：**审清旧失败与配置 → 机械闭环 → 小规模语义诊断 → 原正常门槛回归 → 四主臂两工作流 → 未见数据与泛化确认。保留原 48 项要求和旧状态；本版通过显式补充协议调整实现与实验安排，不抹除原失败。[R2]

---

# 0. 阅读方式与证据边界

正文使用三种表述。**已有事实**来自固定 GitHub 报告、代码及本次核实的公开文献；**原因判断**是根据失败链与实现作出的推断；**改进方案**是本版待开发、待检验的设计。不得将第三类写成第一类。

本次检查包括暂停报告、R9、R6/R7、R8 固定/自由结果、direct_support 设计、读取协议验收、GroundedMemoryRecipe 与 compact_material。对本地封存 HTTP、数据库、完整 895 文件文献目录未作独立读取；仓库报告中的这些核查仍归属于原报告作者。[R2–R9]

原 v13.2 状态仍是 E0 NOT_PASSED、D4 NOT_ADMITTED、Product NO_GO；48 项为 4 PASSED_SCOPED、27 PARTIAL、1 NOT_PASSED、16 NOT_VERIFIED。不能把 reference 测试或本规划生成算作原要求通过。[R2]

新规划并非承诺必然超过 baseline。所谓“完成算法优势开发”，在这里具体指：将候选优势落实为可接入的算子、可检查的不变量、可复现的实测与明确的失败退出条件。真实优势必须由公平比较产生。

## 0.1 本版相对 v13.2 的修订

| 内容 | 保留 | 修改 |
|---|---|---|
| 真实事件与工具观察 | 原身份、角色、owner、hash、投影 | 不再让模型重复填写确定性值 |
| direct_support_v1 | 触发与支持分离、历史来源、字段绑定 | 降低手工元数据输出负担；不把“已存在”再写成新功能 |
| 单次维护 | writer1 / repair0 的成本边界 | 维护是一个机会，不是必须提交；分开触发、支持、事实增量 |
| patch/CAS | 实际 record ID、读取版本和冲突 | 未改 scope/support 自动按明示算子语义保留；禁止默认整对象清空 |
| 有界交付 | 当前真实请求、共同预算、显式追加读 | 从 metadata-first 改为完整证据单元优先；审计视图与模型视图分离 |
| 研究收口 | E0、两工作流、强简单对照、失败账本 | 限制开发轮次；不足的来源规模通过明确协议修订，而非死守名义题数 |

# 1. 当前失败：先区分已实现、已启用、实际有效

## 1.1 最新事实与不能越过的结论

| 观察 | 已有证据 | 正确判断 |
|---|---|---|
| R9 核心更新 | 15/15 命中原 ID、核心偏好与更正来源正确 | 原记录身份改善；三接口均通过，尚无新接口独立优势 |
| R9 查询回答 | 13 scoped 正确、1 partial、1 历史错误 | 不是完整事实正确率，也不是独立 Judge |
| R9 查询后维护 | 8 不必要提交、1 rejected/pending、6 no_change | 6 次额外版本、2 张重复/冗余卡；维护终态损伤必须单独计分 |
| R9 来源设置 | support/read protocol 使用 legacy | 不能将其失败直接归为 direct_support_v1 的已启用效果 |
| R6 direct_support | 已实际启用；21/24；仍有来源误选 | 开关不是充分修复；增加来源字段也可能增加形状错误和材料成本 |
| R7 | 21/24，2 中断，1 虚假持久保存答复 | 原 E0 尚未通过；不能拿 R9 的专项更新替代 E0 |
| R8 | 固定派生 0 语义生成；自由预取有正文遗漏 | 保留确定性派生，但尚未证明自由 Agent 的历史效用 |

R9 来自五个已曝光事项 × 三接口，不是 15 个独立新场景；三接口的核心更新均正确，故不能把“15/15”归为句柄或回链的净收益。[R3,R4]

## 1.2 失败链与优先级

**F1，查询后事实污染。**询问仅提供触发，不支持重新陈述的偏好；现有边界仍给 Writer 机会把历史内容/Host 回答重新当成事实输入。角色和 hash 正确不等于语义支持。[R3]

**F2，范围与语言被破坏。**整卡 update 清空结构 scope，或丢掉“通常、本季度、仅设计审查、其他会议除外”；英文来源要求中文保存时，scope 标 Chinese 不等于正文真是中文。[R3,R5]

**F3，证据存在但正文没送达。**R8 预算被元数据消耗，R9 历史错答时旧 r1 正文未进入 HTTP。history index、非空候选和真实送达须分别测量。[R3,R6]

**F4，交互协议的失败。**R7 显式检索游标与普通包快照错配；后续 selected_snapshot_v1 有工程修复，但仍需在新真实闭环中复验。不得放宽 cursor guard 或改用最新结果替代旧快照。[R5,R8]

**F5，保存承诺早于提交。**业务或原事件确实保存，不自动等于语义卡保存。Host final 后的成功提交不能倒过来证明 final 时的承诺真实。[R5,R8]

**F6，过多结构与重复输入。**R6 将支持对象填入值字段，耗尽 12 次生成；R9 输入 888,705、输出 10,678 token，输入占约 98.8%。不能只减少输出或调用数；必须测完整请求中的材料、schema、历史与重复部分。[R3,R7]

# 2. 文献调研：采用什么，不采用什么

以下只将作者实际研究问题用于设计，未运行外部方法，也不把作者分数迁移为 MiLAi 预期分数。

| 文献/方法 | 可支持的设计启发 | 不能推出的结论 |
|---|---|---|
| EAL-Bench | 分开错误形成、错误传播、合法使用；保留 faithful 诊断臂 | 不能声称首次发现错误记忆产生行动依据；oracle 不能进入方法运行时 [L1] |
| PPMF | 来源权限由平台维护，不能由摘要措辞升级；真实工具封装也可能携带外部不可信文本 | 这是固定风险政策下的授权边界，不是任意自然语言蕴含检查；不照搬一维信任梯度 [L2] |
| Hindsight | 事实、经历、总结、信念与 retain/recall/reflect 的区别 | 类型或“证据与推断”命名本身无独立创新 [L3] |
| HiMem | Episode/Note 与再整合是近邻；需要比较范围保持而非只比较标签 | 双类型不构成 MiLAi 的独立新颖性 [L4] |
| DeltaMem | 相关经历可以共享基础并表达增量 | 其残差经验树不同于本版事实 patch；不能把“增量”一词当首次贡献 [L5] |
| LongMemEval、Lost in the Middle | 检索、阅读、时序和证据位置必须分开评价 | 更长上下文、更多元数据或检索非空不保证使用正确 [L6,L7] |
| JSONSchemaBench | 结构约束的覆盖、效率与任务质量需分别测 | 合法 JSON 不等于来源正确、语言正确或语义完整 [L8] |
| RFC 6902 | 明确局部操作、前置 test 与失败语义 | JSON Patch 不是研究新算法，也不提供语义验证 [L9] |
| LLMLingua-2 | 可将抽取式压缩作为条件性外部对照 | 不能假定 token 删除保持否定/范围；第一阶段不新增压缩模型 [L10] |

**本版不采用：**新的常驻语义 verifier、每次查询一个反思代理、RL 训练写入策略、复杂残差树、跨领域巨大 ontology 或一套独立授权平台。这些不是没有价值，而是尚未触及当前最早断点，且显著增加验证成本。

PPMF 的公开论文已涉及逐 claim 的来源约束和参数级支持绑定。EDM 必须定位在“良性多轮维护中的冗余/错误改写、范围保持与成本”，而不是重新命名一个权限防火墙。其与 CEP 的组合是否有净价值，仍需对照。[L2]

# 3. 收敛后的算法：两个算子，复用其余能力

定义同一逻辑服务的记忆状态为 M=(O,S,I)。O 是不可变公开事件与操作观察；S 是有版本、范围、支持关系的语义记录；I 是可重建索引。它们不是三个独立真相库。

一次边界的候选过程为：

```text
Delta = 未消费的真实用户事件 + 实际工具观察
C = 同一普通检索器选出的旧记录/历史候选
P = CEP(C, 真实材料预算)
D = 一次 Writer(Delta, 只读旧状态, 公开维护合同)
M_next = Commit(EDM(M, D, 实际来源与读取版本))
```

模型输出的是 `no_change` 或小批量事实增量，不输出一份重新定义可信来源的“完整事实世界”。程序决定身份、版本、精确继承、字段投影、执行回执和事务；模型仍决定哪一段话表达新事实、怎样解释适用范围。

## 3.1 五项有限不变量

**身份不漂移：**由实际 read handle 绑定 owner、record ID、读取 revision 与值 hash；无 token/版本自动补正。

**未改字段不漂移：**不在 patch 中的 content/scope/支持关系保持原字节/规范 JSON 身份；不会因为省略而被清空。

**读取不自动升级证据：**检索结果或 Host 答复不因再次出现而取得新的用户来源、当前有效时间或更高授权。

**完整交付可追踪：**只有真正进入实际模型请求的完整单元才算 delivered；截断片段、指针、遗漏另列。

**只对已完成效果作承诺：**保存回执区分原事件、字面观察、语义卡、no_change/pending；历史版本可读不等于允许当前业务操作。

这些不变量能约束机械行为，不能保证模型把“你记得我喜欢什么吗”错误标为“用户再次确认偏好”时一定被识别。该失败仍必须由真实语义实验发现，不能用哈希或 schema 宣称已解决。

# 4. EDM：基于证据增量的维护

## 4.1 一次维护机会，不等于一次写入义务

复用已存在的 trigger/support 分离。trigger 只标识这轮处理；support 明确指出事实依据；delta 标识相对于旧状态的变化。历史支持可以合法继承，不能要求所有字段都重新引用当前 User。[R9]

Writer 输入只包含：未消费真实事件；其所需的已选旧记录/原支持摘要；公开 patch 合同。Host final 与已注入 memory packet 不作为新的用户事实证据。Assistant 内容可按 agent_experience/plan 保存，但不得冒充 user_statement 或 tool_observation。

默认仍 writer≤1、repair=0。没有未消费事件时可由程序确定性跳过；有新用户消息时不按问号、语言、案例名决定跳过，而由同一个 Writer 判断 no_change 或真实更正。带更正的问句必须可以更新。

## 4.2 提案格式尽量小

以下为新合同草图，并非现有 CLI 参数。m1、e2 是当前包中真实发行、不可跨 owner/快照使用的短句柄。

```json
{
  "target": "m1",
  "changes": [
    {"op": "set", "path": "/content", "value": "设计审查改为周四下午",
     "evidence": ["e2"]}
  ]
}
```

`changes:[]` 为明确 no_change。不让模型输出 owner、hash、全部旧 field_support、数据库版本号和可从句柄唯一获取的字段；这些由已验证句柄及明示编译规则产生并写入实际 commit receipt。程序不是静默修复错误提案：原请求、解析绑定、继承结果、拒绝理由都保留。

普通用户不用提供 ID。模型仍要从真实候选中选择；相似度只用于召回候选，唯一结果也不是语义身份的证明。目标歧义时保留原始事件和 pending，不偷偷 CREATE 替代 UPDATE。

## 4.3 支持关系的更新规则

| 操作 | 内容/支持效果 |
|---|---|
| no_change | 不增加语义 revision，不更新时间有效性，不替换原支持；允许单列访问统计 |
| set 同字节值 | 视为机械 no_change；不能仅换成当前问题来源就生成新事实版本 |
| set 新值 | 明确选择改变依据；检查真实叶、角色、owner、版本；新语义仍 model_interpreted |
| 未提到某个 scope 字段 | 精确保留其旧值与旧支持；不是重新推断它仍然正确 |
| 显式 remove/retract | 要求改变依据；移除及理由进入历史，不能把 null、未知和空集合混为一谈 |
| 新确认同一事实 | 可追加独立观察/支持边，不覆盖旧事实时间，也不人为提升授权或重复卡数 |

机械要求可使用“本次未消费外部事件参与新变化”，但不能简化成“必须只引用最后一条消息”。延迟处理的真实旧事件仍可能属于未消费 delta。来源集合不等于语义蕴含，原文证据要可供复核。

## 4.4 限定 scope 与正文职责

首版允许 `/scope/<leaf>` 的局部 patch，默认拒绝无明确操作的整个 scope 替换；字段缺失表示保留，不代表删除。完整改写正文属于显式操作，应单独审查否定、频率、数量、时效及对象范围。

首次形成尽量采用“原始陈述/证据 span + 简短摘要”，避免把“素食”扩成“避免所有动物制品”。摘要不是新的授权来源。对中文保存要求，正文语言与表达完整性都评分；原文保留只能作为降级，不算满足目标语言。

事实修订与仅改变展示语言分开。翻译或重新措辞可改变视图，不应自动刷新事实的有效时间。第一阶段不开发通用自动翻译验证器，也不以字符比例假装语义语言测试通过。

## 4.5 后台写回不得污染已正确回答

原 Reader final 先封存，随后维护写入另取终态；两者分别评分。对纯查询样本，检查事实值、scope、来源归属和 revision 是否异常变化；访问计数或索引统计不计事实写入。

如果 Writer 仍把纯查询解释成新断言，本版不承诺机械过滤必然阻止。先做固定输入诊断，比较“全对话形成”与“delta-only + 只读旧状态”；若仍高频误写，降低语义自动维护范围或保留原文，不增加纠错代理掩盖失败。

## 4.6 事件消费与事务不能靠一个 turn 布尔值

将处理状态记录在原服务内：每个真实 event 有 observed / consumed / pending 身份，消费凭据关联实际 proposal 与效果。提交成功只确认该 proposal 明确处理的事件；同轮存在一条成功Host写入，不能据此跳过剩余更正或工具观察。

语义 no_change 也保存轻量处理凭据，而不增加事实版本；这样下次不会仅因相同历史再次可见就重新维护。pending 保留原事件、拒绝理由和预算终态，不悄悄标为已消费，不默认自动重试。后续新指令或另行批准的恢复可以显式处理它。

生产接入须在同一受控事务/锁边界完成 record revision、支持关系、proposal receipt 与消费凭据；失败前后必须可恢复。若现有SDK不能原子覆盖这些对象，则先使用 journal/prepare-commit 标记证明恢复一致性，不假称获得了原子性。参考内核只计算状态转换，不实现这部分事务与水位。

# 5. CEP：正文优先，审计信息不占满上下文

## 5.1 不继续把严格可逆元数据压缩当主要目标

现有 direct_support 压力包已出现完整历史减少；当前 recipe 仍含 metadata-first 分配描述。新设计把“服务端能审计”与“模型需要看到”区分开。[R8–R10]

模型可见单元保留：短来源/记录句柄、角色与 basis、当前/历史标记、必要时间、实际正文或字面值、完整相关 scope。完整 owner/hash/祖先来源图/配置身份/回放资料留在已有服务端审计对象，短句柄精确绑定它们。

这不是端到端无损文本压缩：模型少看了审计字段。准确表述是“有服务端可追溯绑定的最小证据展示”。角色、当前/历史、否定和范围不能因为被视为 metadata 就删掉。

## 5.2 先只改变包装，不改变召回

第一轮固定候选 ID、rank、版本及 source ranges，只比较旧 metadata-first 与新 content-first。按原候选顺序尝试完整单元；超预算则显式遗漏，继续尝试后续可容纳单元。一次实际请求用真实 tokenizer 精确计量，不用字符数代替 token。

不把一个空的 Source 头、历史指针或前几个 token 算作完整证据。过大的原文可提供带 offset 的明确 fragment，但必须标明 partial，scope/否定不完整时不能升级为完整事实依据。基础实现先只收完整单元，避免复杂语义压缩。

## 5.3 后续才检查版本对与局部扩展

如果关键旧版本没有进入候选，而非仅被包装挤掉，再启用独立变量：对已选 identity 提供当前版本与一个真实前驱/相关历史片段。全部来自实际历史索引，并计入同一 max-records 和 token 预算。

版本对不是根据 gold 挑旧版本；也不能固定“越新越真”。当前和历史都显示有效/观察时间及修订关系。没有绝对时间锚点就保留相对表达和 unknown，不用机器运行日期补成事实。

这项扩展同样提供给 Receipt-RAG+ 和适配能力允许的对照；外部 SDK 不支持完整版本时如实记录 capability gap，不能伪造历史或 CAS。

## 5.4 读取、缓存与快照

复用 selected_snapshot_v1：ordinary 与显式 search 的结果都绑定各自快照，分页指向实际发行快照，不回退到最新集合。新版本只使旧写句柄的 CAS 失效，仍可按真实快照读取其历史内容。owner/会话不匹配、失效 handle 或被删除 Source 返回明确 unavailable/rejected。

缓存按 owner、请求、读取版本、投影版本和策略身份管理；只在依赖真实变化时失效。缓存避免重新构造/检索，不意味着缓存文本再次进入 LLM 不计 token。

每个 ordinary 包和每个付费追加读都检查实际材料；另检查完整请求的 system/schema/user/history/output reserve。所有窗口均无可放下的证据时，返回预算不足及可用读取入口，不静默截断或无限自动再读。

# 6. 保存时序、操作观察与恢复闭环

## 6.1 明确“保存”的四种效果

`event_captured`、`observation_projected`、`semantic_committed` 和 `no_change/pending` 分开。工具/运行时在 final 之前已经完成的结果，才可进入 final 的确认依据。后台成功不能追溯支持过去的“已保存”。

普通 Host 可只读记忆，但用户明确要求保存时，必须有能在 final 前返回真实效果的提交路径。建议复用简化后的显式 `commit_memory` 行为：由模型正常选择调用，一次消费相同维护 slot；后台对同一已消费事件不得再次提案。不使用 required tool 强迫成功。

只读 Host + 后台维护也保留为独立系统设置：它只能承诺已完成的原始事件或投影，不能提前承诺语义卡。两个设置的功能、时延和调用都单列，并对所有方法公平开放。不得用一个模糊 Saved 回执掩盖差别。

## 6.2 确定性工具观察继续保持

预订/标签、文稿版本/审批/发布继续通过公开字段合同映射；真实工具封装不等于其中任意自由文本都可信。未知工具原样捕获，不自动猜 success/no-effect，不自动把 external 文本提升为业务确认。

同一事件可支持多个有限字段、对象或记忆。幂等单位是实际 event、对象、字段、投影规则版本，而不是“出现一次来源就禁止其他合法使用”。本轮先审计现有 observation.py，不重复造投影库。

## 6.3 W1 / W2 / W3

| 窗口 | 应恢复的东西 | 禁止行为 |
|---|---|---|
| W1：效果可能发生，回执未持久化 | 通过公开 discovery 查询实际状态 | 仅因 memory 空就重复 mutation |
| W2：回执已存，记忆投影未完成 | 幂等重建投影/恢复待维护状态 | 重新执行业务动作 |
| W3：语义提交已存，final/ack 丢失 | 返回原提案回执、保留版本 | 再造一个版本或宣称新的业务效果 |

协作锁、SQLite 事务和 CAS 的保证范围需精确声明。跨非合作写、外部并发和任意 API 的 exactly-once 仍不承诺。Mem0 的 snapshot-before-close、新进程同路径 reopen 必须在真实 SDK 下复验，Mock 通过不能替代模型质量。

# 7. 已有实现复用与开发边界

| 位置 | 复用/修改任务 | 不做的事 |
|---|---|---|
| `memory/service.py` | 现有 source/direct_support、read handle、CAS、commit；加入显式 patch 继承与 no-op 规则 | 不重写旧库为已验证数据，不把自然语言标 true |
| `memory/service_tools.py` | 简化模型可见提案；真实候选 alias 与实际提交回执 | 不自动默认最新 Source，不让用户输入 UUID |
| `memory/observation.py` | 复用有限字面投影和事件幂等 | 不从 hidden world/scorer 投影 |
| `methods/grounded_memory.py` | delta-only 输入、CEP、实际选中/送达记录 | 不再全量序列化审计图给 Host |
| `methods/compact_material.py` | 旧 profile 保持；新 content-first profile 独立 | 不将精简审计字段称无损语义压缩 |
| `contracts/read_protocol.py` | 已发行快照、cursor、有限错误反馈 | 不自动再检索/替换版本 |
| `contracts/common_boundary.py` | 共同节奏、总 admission、能力差异 | 不用非 M CRUD 占位制造 schema 差异 |
| `runners/v13_1_d0.py`、`v13_1_p5_compare.py` | 只组装新冻结设置与账本 | 不埋方法逻辑，不触碰 gold 路由 |

新 helper 可放在 `methods/evidence_delta.py` / `methods/evidence_pack.py`，这是建议新路径，不表示当前存在。Provider 只处理通用请求与容量；算法不移回 provider。

工程第一任务是生成实际有效 profile，而非堆叠开关：将 support、read protocol、host profile、writer cadence、material、capture/commit feedback 的最终值与交互写入一次 manifest；运行时检查真的进入对应分支。R9 的 legacy 事实说明“仓库有功能”不能代表实验用了功能。[R4]

# 8. 基线：既要有外部系统，也要有足够强的简单方法

## 8.1 主表四臂

| 方法 | 共同能力 | 该方法独有部分 |
|---|---|---|
| StrongRawRAG+ | 相同事件、owner、工具、预算、有界交付、显式追加读 | 原文 BM25+dense，固定融合 |
| Receipt-RAG+ | 同上，且有相同字面投影、真实回执与恢复合同 | 简单当前状态/历史投影 + 原文检索；可选一次付费滚动摘要 |
| Mem0-TraceEqual | 相同合法事件 carrier、真实 SDK、共同 Host 与实际计费 | 锁定版原生 infer=True 摄入/检索；不伪造版本能力 |
| MiLAi v13.3 | 同上 | EDM 的版本/支持保持 + CEP 的证据表示 |

FullHistory、NoMemory 是参考臂；Ordinary、Prompt-only、v13.2 最新可运行 direct_support 是机制对照。旧 R9 legacy 不能成为唯一内部对手。只读 NeverWrite 可作为退化控制：它应避免写污染，但会漏掉真正更正，故不能凭单一安全指标获胜。

SimpleMem-Text 在既有接入通过后增加公共任务外部对照；按实际算法预算区分质量配置和联合预算，不用某个共享上限耗尽直接判语义劣势。只使用核心后端时明确写“后端比较”，不称完整 native ask/反思复现。

## 8.2 最近邻与主张覆盖

若论文主打“证据与推断区分”，安排 Hindsight 的忠实小切片，或明确未复现并收缩主张；主打双类型则需要 HiMem，当前不优先该主张。若强调权限安全，应对照 EAL/PPMF 的实际能力，而不是只比较通用 RAG。本文优先研究良性维护的事实保真与资源代价，不扩大为完整防攻击平台。[L1–L4]

外部系统的版本、提示、摄入时机、模型、embedding、原生反思、重试和历史能力必须登记。当前托管平台成绩不得与 OSS pin 混用。每个 baseline 获得同等开发配置选择机会，不用更差的 prompt、少给来源或跳过实际 SDK 操作制造优势。

# 9. 实验：先隔离变量，再证明整个闭环

## 9.1 E0：原门槛与终态回归

原 24 正常检查、22/24 门槛及来源/虚假保存限制保留。新固定版本重跑作为新 cohort，旧结果不可覆盖。两旧 update 专项要求：原 ID、真实更正支持、范围保留、旧版本可读、final 正确，并且查询后终态未再次损坏。

工程侧先完成游标解析、snapshot/close、字段 patch、观察投影；普通语义失败不阻断无关的离线机制实验。但未达 E0 时，不把四臂诊断称为原 D4 正式准入。任何门槛修改要单独批准和记录。

## 9.2 E1：维护的最小 2×2

固定真实可见输入、模型、初始 bank、一次维护额度与 reader；比较：

|  | 整卡重写 | 有明示继承的 sparse patch |
|---|---|---|
| 完整已完成对话作为形成上下文 | 旧式形成 | 分离 patch 效果 |
| delta-only + 只读旧状态，Host final 不作新事实 | 分离输入分工效果 | EDM 组合 |

四格都使用相同真实来源检查；旧 R9 legacy 另外单列，不与已启用 direct_support 混成一个条件。每个样本记录维护前后事实、scope、支持及版本，不能只看 Reader。

开发用已曝光五事项及固定反控，不反复消耗新来源。未见机制测试建议至少 40 个独立场景作为预算起点，覆盖纯查询、明确更正、带更正的问句、再次确认、临时覆盖/撤销；最终量由 pilot 方差与实际来源决定。

纯查询预期 no_change；带更正的问句必须更新；重新确认可以保留独立观察但不造冗余事实版本。手工设计的负例是机制压力，不是自然错误发生率。

## 9.3 E2：包装、历史候选与阅读分开

第一轮候选/版本/排序固定，比较旧 full/compact 与 CEP；预算可在无模型离线阶段用 512/1024/2048/4096 分析，质量主表只使用开发前冻结的共同预算。检查完整正文、scope、否定、字段值是否真的进入最终 HTTP。

第二轮才比较“原候选”与“同 identity 的有界当前/历史扩展”；这属于候选因素，不能混称 CEP 纯包装收益。All-delivered 仅在容量允许时用作消费上界诊断，不给主方法免费全历史。

指标包括证据完整交付率、各类遗漏、Host 显式补读、当前/历史准确性与完整输入 token。纯信息密度指标不能代替问题质量，greedy 选择没有语义最优保证。

## 9.4 E3：自由 Host 与生命周期

先四主臂 × 六个已曝光文稿故事＝24 轨迹；预订工作流另六故事，合计 48 开发轨迹。不立即展开 14 设置。质量 24 次生成与联合 12 次条件分别冻结；所有 Writer/Host/native/restart 共用实际持续 admission。

正式预算起点仍为 60 个基础任务 × clean/一个预分配异常条件 × 四方法＝480 方法轨迹。异常包括 partial、known no-effect、unknown-effect、unknown-no-effect、stale；基础任务需有结构差别，而不只是换 ID。读写完成、语义成功、恢复正确和额外副作用分别评分。

## 9.5 E4：公共锚点与必要的记忆依赖

复用 MERIT 的官方任务/工具/checker 比较实际行动，主表区分 dependent、完整 arc 和成本；保留合法业务查询，NoMemory 能做成的任务不伪造记忆必要性。

MemSyco 使用 scope/valid/personalized 三任务并分开评分；其已曝光来源不能成为新测试。LongMemEval 可在有独立未用来源时提供更新/时间/拒答补充，不代替生命周期。EAL 仅在方法确实支持授权语义时使用，不从 gold 构造“真实回执”。

# 10. 泛化、长程与数据修订

**任务泛化：**按来源组、工作流模板或原始历史划分，而非仅不同参数 seed。两已参与设计的工作流是跨工作流验证，不是未见领域零样本。

**工具泛化：**冻结核心算法后，在一个未参与算法调参的新公开 schema 上只填写字段/效果映射；不得为其另加选择器、案例判断或更长 prompt。没有公开语义映射的字段继续未知。

**跨语言：**中文原文、英文原文、混合更正与要求输出语言分别测；跨语言检索命中、目标语言正文和范围保持不能合成一项。不能针对语言切换方法。

**模型泛化：**先固定旧 bank 换 reader，另做重新形成 bank 的跨家族端到端实验，两者分开；服务未提供则保持未验证，不把同家族不同端口计作新模型。

**自然长程：**方法在小样本过关后，再对 2 owners、每人 20–30 sessions 的自然累积任务验证；不加随机无意义噪声制造优势。重复纯查询 1/5/10/20 次可作单独不漂移压力，但不能代替自然长程。

MemSyco 的分组容量按既有 source-group amendment 复核，保留曝光与预留清单。新规模在测试访问前公开修订。仅预留未读取的内容只有经记录可审计确认、且未参与方法选择时才可能重新分配；否则继续排除。题数不足不是放弃研究的理由，也不能靠已曝光内容填满 100 题。

# 11. 指标与算法优势的判据

| 主要指标 | 分母/解释 |
|---|---|
| Unsupported Rewrite Rate | evaluator 判定无事实增量的边界中，新增无支持语义版本的比例 |
| Valid Update Recall | 真正更正/撤销应生效的边界中，正确生效且范围保持的比例 |
| Scope/Negation Retention | 受影响事实的主体、时效、频率、否定与排除项分别检查 |
| Post-read Drift | 从维护前正确状态到维护后错误状态的比例；索引/访问统计不算事实写入 |
| Complete Evidence Delivery | 评分所需依据进入实际请求的完整度；只用于评价，不进入 runtime 排序 |
| Native/Lifecycle Success | 官方任务成功、完整生命周期成功、错误提案及真实副作用单列 |
| Cost and Latency | 所有形成/检索/反思/Host/修订/恢复/失败费用及可测时延；冷启动另列 |

**机械通过目标：**固定控制中无身份替换、无省略导致 scope 清空、无无效 CAS 提交、无超预算 packet、无 empty-body 伪 full。它们不能推出任意自然语言正确。

**开发通过目标：**原 E0≥22/24；指定旧错误查询不再造成无支持写回；真正更正不能因保守策略普遍漏存；旧历史问题关键证据被送达并正确使用。这些是开发决策门槛，不是统计置信保证。

**研究优势至少满足一条，且无隐藏退化：**

A. 同预算下，错误写回/完整生命周期失败显著下降，正常任务效用非劣；或 B. 效用非劣时，全生命周期成本或实测时延降低。不能只报告拒绝率、工具成功或输入 token 减少。

非劣界可在 pilot 后、正式运行前约定（例如 5 个百分点，只是规划例值）；置信区间不足时写证据不足，不以 p>0.05 认定无退化。按来源/arc/基础任务配对 cluster bootstrap，预定主比较和多重检验；15 轨迹/45 消息不算45独立样本。

未知/中断/未运行分开：报告计划完成率及质量结果界，不删除失败后再算漂亮准确率；工具提供方故障也不伪装成语义错误。

# 12. 成本与调用优化：不把元数据工程变成主要研究工作

R9 的查询后维护占 60,678/899,383≈6.7% 生成 token。仅去掉这些调用，不足以解释整体成本大幅下降；主要应分析 schema、材料、历史和重复请求输入。输入比例也不等于费用比例，需实际记录缓存与计费。[R3]

第一阶段不加一个收费的“是否维护”分类模型。复用单次 Writer 的 no_change 决策；对完全没有未消费事件的边界进行确定性跳过。exact no-op 在提交前合并为无新 revision，不借此退款已发生的模型调用。

稳定 schema/说明放在稳定 prompt 部分；重复 proof 元数据不全量放入模型上下文；候选与 Source ID 使用真实发行句柄。tokenizer 对完整字符串计数，组件统计采用固定顺序边际计数以保持总和一致，避免单独 token 数简单相加产生误差。

每个实验只需一份冻结 manifest：代码/依赖/配置/输入/有效 profile/模型/预算/评分/结果与账本路径。保留必要原始请求、回执、终态及失败，不要求每条无关 shell 命令制作新的独立验收文档；原已有审计和封存不删除。

每个核心假设最多两轮已曝光开发修订后复盘；没有改善就采用更简单方法、收缩主张或停止该分支，不无限生成 R10/R11…却没有正式比较。

# 13. 开发工作包与实际交付

| 包 | 任务 | 输出与验收 | 依赖 |
|---|---|---|---|
| W0 | 核对最新代码及实际 profile，收口旧 R9/生命周期评分 | 失败→实现→启用→效果矩阵；不新增付费 HTTP | 无 |
| W1 | 读取/提交原语复验：快照、owner、CAS、close/reopen、保存效果 | 实际 SDK + 有限 Mock；旧错误控制可复现、新路径有限通过 | W0 |
| W2 | EDM：delta Writer、小提案、显式继承、no-op、真实支持 | 稀疏更改不丢 scope；问题/更正语义对照 | W1 |
| W3 | CEP：正文优先、短快照句柄、实际 HTTP 计量 | 相同候选的完整交付与成本；不改变 rank 造收益 | W1 |
| W4 | E0 与 E1/E2 真实开发对照 | 新冻结首尝试；失败、预算和终态分开报告 | W2/W3 |
| W5 | 四方法两工作流、小规模质量/预算两设置 | 先48开发轨迹，再按冻结规模正式采集 | E0 与协议门槛 |
| W6 | 未见公开任务、模型/工具/语言泛化、统计 | 形成最小可投稿证据包；未完成项明示 | W5、来源服务可用 |

各工作包以直接验收证据结束，不以消耗的天数或产生的归档数量结束。W2与W3可在接口冻结后独立开发，但同一方法/同一文件保持单一负责人。真实模型成本先由小切片估计，再冻结正式预算；Writer语义仍失败时按两轮规则转向。

# 14. 参考实现、迁移与验收范围

规划包 `reference/core.py` 提供两个独立函数：`apply_delta` 与 `pack_content_first`。它们不是 MiLAi 的 drop-in adapter，也不访问真实 Store/MCP/provider。

本地 `python -m unittest -v` 实际通过 32 项标准库测试。覆盖 exact no-op、未改 scope/support 保持、显式删除、CAS/owner/hash、assistant/retrieved 不能充当外部事实、拒绝时不部分修改、Unicode/bool边界、完整证据 packing、预算与省略、当前/历史标签和快照关联。

**关键反例也被测试：**一个合法 User 问句仍可能被错误引用为偏好事实。结构内核会标记 `semantic_verification=not_performed`，并不假装能识别这一语义错误。该测试通过的含义是“明确暴露保证边界”，不是修复语义问题。

包装测试使用 `len` 作为可注入的度量函数，仅验证精确预算算法；它不是 Qwen tokenizer 结果。真实接入必须使用现有本地 tokenizer/chat template，并检查工具和系统说明在内的完整请求。

迁移保持旧默认、旧记录与旧 profiles。新代码默认 opt-in；旧字段无逐字段支持时保持 legacy/unverified，不回写成新验证状态；已有错误记录可单列修复任务，不改原实验库。方法迁移需新的 source/entry freeze，不更新旧运行身份。

这次交付没有实现生产级新记录创建、删除撤销传播、SDK事务、事件水位、付费模型调用或完整恢复编排。这些明确属于 W1–W6 接入任务，不把独立原型当作完成仓库开发。

# 15. Go / Simplify / Stop 与论文收口

**Go：**在相同支持/权限/预算下，EDM减少无支持写回且保留真实更正；CEP送达更多有效正文并改善问题质量；组合结果在强简单方法前仍有净价值。

**Simplify：**若 Prompt-only 同样有效，保留提示；若 sparse patch不增益，保留简单更新；若 Receipt-RAG+同样好，接受简单投影；若普通 query/working state足够，不上Attention。

**Stop：**需要gold构造ref、按案例路由、静默补源、宽松业务授权、丢掉失败或让多Reviewer改答案才能提升时，停止该方法。来源/服务不足时停止相应正式主张，不停止独立可完成的工程和机制验证。

建议首篇论文的主张是：**对工具使用Agent的长期记忆，证据增量维护和有预算的正文交付能否共同改善“维护后事实保真—任务效用—全生命周期成本”。**类型、回执、CAS、source hash、JSON patch不是五项独立创新。

研究表格应至少包括：四方法整体任务/成本；查询后终态损伤与真正更正召回；EDM与CEP的拆分；两工作流及一个明确未见维度；全部异常和失败界。新颖性相对 EAL/PPMF/Hindsight/HiMem/DeltaMem 的差异在投稿前再次核查。

最终只报告已验证的有限机械保证和实测优势。优雅的标准是更少的重复生成、更清楚的证据关系、更低的可测总开销，而不是更多模块、更多元数据或更多检查点。

# 附录 A. 原要求的延续与补充协议

原48行不覆盖、不清零、不自动PASS。本版继承所有原任务：E0正常使用、E1派生/交付、E2回链/修订、两工作流、公开任务、来源组、模型评分、统计、长程、迁移/恢复/删除与复现。

本版新工作包对应原组别：W0→原D0/证据收口；W1→原D1/协议与恢复；W2→原D3/E2；W3→原D2/交付；W4→E0/E1/E2；W5→原D4/E3；W6→原D5/E4/泛化。这里是组级映射，不能声称已逐条重新验收48项。

实施前逐行追加 `amended_by / new_evidence / status_reason`，保留原值。来源样本量、允许的作用域继承、新编译器自动继承规则、只读/显式保存模式等有改变时，以独立 amendment 记录，不把“自动继承”藏进旧“禁止自动补源”配置里。

原规则禁止的是为错误提案创造支持。新规则允许的是模型显式选择 patch 后，程序精确保留未改字段已有支持；改动字段必须有显式依据。两者不能混淆。

# 附录 B. 来源与核查范围

全部 GitHub 项目来源固定到 `22addcbc378a75d7f854ddc4127eb80f45ca52fb`，除 R0 原始附件和 R1 实时PR元信息外。本次未复现作者模型成绩。外部文献摘要核查与全文方法核查在下面分别注明。

[R0] 用户提供的 `milai.txt`：总方向、最早断点、程序/模型分工、单逻辑MemoryService、baseline和Attention边界。原SHA是历史快照，不作为最新仓库事实。

[R1] PR #79 元信息，2026-10-02读取：open/draft/unmerged，head `22addcb`。https://github.com/minguselandy/MiLAi/pull/79

[R2] 暂停总结与状态。https://github.com/minguselandy/MiLAi/blob/22addcbc378a75d7f854ddc4127eb80f45ca52fb/MiLAi-Lab/docs/V13_2_PAUSE_STATUS_20261002.md

[R3] R9全部结果、来源失败与费用。https://github.com/minguselandy/MiLAi/blob/22addcbc378a75d7f854ddc4127eb80f45ca52fb/MiLAi-Lab/docs/V13_2_E2_R9_RESULTS.md

[R4] R9实际模型前冻结：support/read protocol legacy。https://github.com/minguselandy/MiLAi/blob/22addcbc378a75d7f854ddc4127eb80f45ca52fb/MiLAi-Lab/docs/V13_2_E2_R9_RUNTIME_FREEZE.md

[R5] R7正常门槛、游标、保存承诺。https://github.com/minguselandy/MiLAi/blob/22addcbc378a75d7f854ddc4127eb80f45ca52fb/MiLAi-Lab/docs/V13_2_E0_R7_RESULTS.md

[R6] R8自由Host；固定流另见同目录 `V13_2_E1_R8_CONTROLLED_RESULTS.md`。https://github.com/minguselandy/MiLAi/blob/22addcbc378a75d7f854ddc4127eb80f45ca52fb/MiLAi-Lab/docs/V13_2_E1_R8_FREE_RESULTS.md

[R7] R6 direct_support 实际结果。https://github.com/minguselandy/MiLAi/blob/22addcbc378a75d7f854ddc4127eb80f45ca52fb/MiLAi-Lab/docs/V13_2_E0_R6_RESULTS.md

[R8] 读取协议工程验收与负面材料成本。https://github.com/minguselandy/MiLAi/blob/22addcbc378a75d7f854ddc4127eb80f45ca52fb/MiLAi-Lab/docs/V13_2_READ_PROTOCOL_IMPLEMENTATION_ACCEPTANCE.md

[R9] direct_support已实现的触发/支持分离与继承边界。https://github.com/minguselandy/MiLAi/blob/22addcbc378a75d7f854ddc4127eb80f45ca52fb/MiLAi-Lab/docs/V13_2_DIRECT_SUPPORT_DESIGN.md

[R10] GroundedMemoryRecipe源码，主要读取开头250行的policy/表示；compact_material.py读取全文件。https://github.com/minguselandy/MiLAi/blob/22addcbc378a75d7f854ddc4127eb80f45ca52fb/MiLAi-Lab/src/milai_lab/methods/grounded_memory.py

[L1] Cerruti et al. Agent Memory Is a Surface for Endogenous Authorization Laundering. arXiv:2609.01836，2026。当前检索到摘要/主张，全文HTML本次获取失败；使用此前已读官方任务说明，不新增性能数字。https://arxiv.org/abs/2609.01836

[L2] Xu et al. Memory Provenance Laundering in LLM Agents: A Non-Amplification Firewall for Persistent Memory. arXiv:2607.29167v1，2026。核查PDF方法、假设和实验范围，并查看第4页公式/图；不复现成绩。https://arxiv.org/abs/2607.29167

[L3] Latimer et al. Hindsight is 20/20: Building Agent Memory that Retains, Recalls, and Reflects. arXiv:2512.12818v1。核查论文HTML方法；不将不同版本平台成绩混用。https://arxiv.org/html/2512.12818v1

[L4] HiMem: Hierarchical Long-Term Memory for LLM Long-Horizon Agents. arXiv:2601.06377，2026。摘要和项目边界核查。https://arxiv.org/abs/2601.06377

[L5] Tan et al. DELTAMEM: Incremental Experience Memory for LLM Agents via Residual Trees. arXiv:2606.03083，2026。本次摘要核查，不声称已审计其实现。https://arxiv.org/abs/2606.03083

[L6] Wu et al. LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory. arXiv:2410.10813。摘要及官方任务说明；不将QA成绩替代真实行动。https://arxiv.org/abs/2410.10813

[L7] Liu et al. Lost in the Middle: How Language Models Use Long Contexts. arXiv:2307.03172。摘要核查；作为上下文使用限制的研究依据，不宣称能解释全部当前失败。https://arxiv.org/abs/2307.03172

[L8] Geng et al. JSONSchemaBench: A Rigorous Benchmark of Structured Outputs for Language Models. arXiv:2501.10868v3。固定v3 HTML核查，后续版本标题可能改变。https://arxiv.org/html/2501.10868v3

[L9] Bryan and Nottingham. RFC 6902: JavaScript Object Notation (JSON) Patch，2013。核查操作与错误处理；本包内核不是RFC完整实现。https://www.rfc-editor.org/rfc/rfc6902

[L10] Pan et al. LLMLingua-2: Data Distillation for Efficient and Faithful Task-Agnostic Prompt Compression. Findings of ACL 2024。作者论文/ACL页面；仅作为候选压缩对照，不采用其效果数字。https://aclanthology.org/2024.findings-acl.57/

补充检索看到 GEM/MemState、Audience-Bound Persistent Memory 等相关主题；本版不据其宽泛主张扩展MiLAi方法，也不声称已逐个复现。资料引用数量不作为开发成果或创新证据。

# 附录 C. 配套文件

`reference/core.py`、`reference/test_core.py`：独立确定性内核与32项测试。

`experiment_plan.yaml`：设计模板，不是现有MiLAi CLI可直接执行的参数。

`failure_to_workpackage.csv`：失败、既有证据、方案、实测与退出标准映射。

`reference/README.md`、`reference/test_result.json`：运行方法、保证边界和本地实际测试结果。

`SHA256SUMS.txt`：本交付文件的校验；不包含自身，也不修改任何旧实验封存。
