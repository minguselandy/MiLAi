---
version: v14.0
date: 2026-09-26
status: DESIGN_READY_IMPLEMENTATION_NOT_STARTED
baseline_commit: 488a4291925c607f6d0dc313a7dcbaf1906a6fad
baseline_source_mapping_sha256: 5c92005f5e7f2b36c6716dcd8cf5ce1c05091f06fe47141c9f37474c6ff9a773
scope: MiLAi-Lab
---

# MiLAi v14 详细设计：跨轮价值、执行依据与持久正文

**采用 Semantic Boundary Hardening 方向，沿现有维护与 ReAct 路径改造。核心是把模型仍需判断的语义与程序已经知道的事实分开，而不是再加一套 State、反思 Agent 或失败审核流程。**

本文基于 488a429 的静态源码核对及 v13 已冻结证据。以下新字段、错误码和行为均为拟议合同，尚未实现或验证。对应 [开发 Goal](MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v14.0_20260926.md) 规定实施顺序、职责和验收状态；本轮只交付文档。

后续状态：用户已于 2026-09-26 明确授权执行，当前实现进展见[开发记录](CONTEXTUAL_USER_MEMORY_V14_DEVELOPMENT_20260926.md)。本文保留原设计时的提案与未验证声明，具体实现和验收以开发记录及最终结果为准。

执行后的[结果报告](CONTEXTUAL_USER_MEMORY_V14_RESULTS_20260926.md)为 IMPLEMENTED_WITH_OPEN_SEMANTIC_FAILURES：A–D 与规定的有限验证已交付，语义基线未通过；V3 条件未满足，不恢复比较研究。本文下方“本轮只交付文档”等表述保留为规划时点记录，不表示后续实施尚未执行。

## 1. 源码事实与建议的修正

| 当前事实 | 位置 | 对本次设计的约束 |
| --- | --- | --- |
| 已有 semantic_frontier，输出阅读范围、committed_changes、business_outcomes、未决操作与失败尝试 | [contextual_maintenance.py](../src/milai_lab/runners/contextual_maintenance.py) | Persistence Frontier 应是此投影的收敛，不新增第二份观察集合 |
| semantic_finish 检查可信 required ranges、persistence_required 和未决操作，接受完整后清空 pending | 同上 | 缺口在未被可信接入强制要求的普通新观察；不能给每条 benchmark 消息强置 persistence_required |
| 维护说明已要求保存首次有未来用途的承诺；写入规则也说临时事项可以 durable | [contextual_host.py](../src/milai_lab/runners/contextual_host.py)、[write_contract.py](../src/milai_lab/methods/contextual_memory/write_contract.py) | 再加同义提醒不是新机制；必须改变未处理语义的显式处置 |
| Host 每次请求已放入 business_outcomes，但目前主要是 call_id／name／status | contextual_host.py 的 business_outcomes 与请求组装 | 新 execution projection 应替换／补足这里，不能重复输入同一账本 |
| RuntimeStore 先记 intent，再保存 result，支持 reconciliation | [contextual_runtime_store.py](../src/milai_lab/runners/contextual_runtime_store.py) | 只读派生执行视图；不重做日志、事务或未知结果重试 |
| BusinessTool 只有 schema 和 execute，没有 read-only／routine 标签 | [contextual_agent_tasks.py](../src/milai_lab/runners/contextual_agent_tasks.py) | 程序目前不能认定“这个工具输出无未来价值”；查询性质与语义价值也不同 |
| MaterialView 管理具体版本／范围与 mN，HostSession 按真实 transcript 更新可见权限 | [material_view.py](../src/milai_lab/methods/contextual_memory/material_view.py)、[contextual_session.py](../src/milai_lab/runners/contextual_session.py) | 复用绑定；字符命中不能变成新的来源权限 |
| apply_content_patch 已有准确匹配、重叠和交付范围检查 | write_contract.py | 新校验应理解 patch 的新旧片段，不能强迫局部修改重新生成全文 |
| compact tool catalogue 已从同一 schema 提取工具／字段说明 | contextual_host.py 的 _compact_tool_descriptions | 先清点实测重复，不能把“工具压缩”重新列成未实现功能 |
| 当前 notes 模板是 contextual-task-v12，source_retention=session、maintenance v4、thinking=false | [当前模板](../configs/contextual-memory-v12-notes-template.json) | 新合同独立配置、明确版本；不覆盖 v13 实验身份 |

需要修正原建议中的三个强假设：

1. **引用来源不等于处理完来源。** 写入正文可能只吸收一条消息的一个事项，来源关联只能作为实际提交事实。
2. **成功回执引用合法不等于 answer 无幻觉。** 模型仍可能引用“消息已发送”，同时错误叙述“审批已提交”。
3. **已分配句柄不等于该字符串只能是句柄。** 本轮分配了 m4，原文也可能恰好谈论型号 m4；需要字面用途例外或新的协议编码，不能宣称集合匹配天然无误伤。

## 2. 目标流程及所有权

```text
可信用户输入／真实工具结果
  → 原有 publish → retain → project → deliver
  → maintenance.pending 中的本轮候选与实际交付范围
  → 同一 Host 选择业务动作／memory_save／必要读取
  → 程序记录真实提交、执行结果及来源关联
  → 精简 frontier：已发生的事实 + 剩余需语义处置的候选
  → 同一次 finish_turn：剩余处置、已完成动作引用、答案
  → 程序核验结构事实；报告真实维护状态
```

Host 判断：信息跨轮是否有用、是否是同一事项、当前理解如何表达、现有记录是否已足够、业务等待应怎样说明。程序判断：来源身份、交付范围、版本、是否实际写入、真实回执状态、协议 token 是否出现、哪些必需处置仍未完成。

持久 MemoryCard 继续表达当前可复用事项；TaskState／work_note 继续承担会话工作内容；本轮 frontier 是维护入口的临时状态，不升级为长期用户画像或第二个决策状态。

## 3. 执行状态与未来用途正交

执行状态分为两种来源，不能混用：

| 信息 | 来源与语义 |
| --- | --- |
| succeeded／failed／unknown | 可信 BusinessToolResult 或已核对 reconciliation；只针对该次调用 |
| not_started／waiting／conditional plan | 用户输入、当前任务或 Host 的计划；不是执行成功证据 |

未来用途由 Host 判断：

| future_use | 语义 | 本版存储映射 |
| --- | --- | --- |
| task_local | 只服务当前限定任务／会话 | 现有工作笔记或 task persistence；无需为每项创建卡 |
| cross_turn | 下一次相关工作仍可能需要，可能跨新会话 | 现有 durable，正文保留事项及等待／生效范围 |
| durable | 跨多个后续任务可复用 | 现有 durable，不等于无限期保留或全局适用 |
| none | 当前没有选择出未来需要保存的变化 | 不新建长期记录；不声称全文均已审阅 |

cross_turn 与 durable 是用途表达，不是两种新数据库寿命。durable 仍受权限、删除、来源保留和范围约束。task_local 也不是“所有任务信息”；未完成事项恰恰可能需要跨会话保存。

共享说明只保留一个判断问题：**若这份观察在下一次相关工作中不可用，是否会丢失用户约定、要求、未履行事项或需要复用的结果？** 明确仅本轮／不要保存的限制优先，不以假想未来收益覆盖它。执行等待不能单独作为 none 的理由。

该问题仍是模型语义判断。新 schema 不会自动消除错误分类；开发诊断必须测它是否比 v13 的全局 not_selected 更清楚、且没有导致所有输入都保存。

## 4. Persistence Frontier：复用现有状态，只处理语义余项

### 4.1 候选从哪里来

以 maintenance.pending 中的准确来源为唯一观察登记；不复制一份来源正文。新直接用户观察必须有处置机会，不能仅让 Host 主动提出 frontier，避免遗漏首个承诺。

其他候选包括可信接入明确要求审阅／保留的观察、真实业务结果以及 Host 根据已读材料提出的未处理变化。程序可以依据来源角色与工具合同选择交付形式，不能根据“pending”“get_”等词确定未来价值。

V0 不引入工具分类模型。没有可信操作性质时，结果仍可进入候选；可将同类未处理结果作为一个可展开组投影，但不能无声归为 none。以后若增加 BusinessTool 的只读／变更 metadata，应由可信适配器提供，并只说明操作性质；只读结果也可能揭示重要新事实。

### 4.2 程序生成的事实

既有 pending 项可增加一个小的、可恢复的语义处置字段；准确来源、turn 身份、阅读范围仍使用原字段。投影收敛为：

```text
unhandled_candidates: 尚无处置的已交付来源／分组
write_facts: 本轮实际提交的当前记录与准确来源关联
execution_facts: 本轮真实业务回执状态
required_work: 必需阅读、可信保留要求、未决操作及失败尝试
```

write_facts 来自实际提交及当前版本，不能由 Host 自报 saved。它允许已写来源不再重复填“来源—卡—版本”表，但界面必须说明：**有关联的提交不代表该来源的全部意义已处理。** 相同消息中“临时语气要求＋新约定”的混合案例必须进入诊断。

### 4.3 最小输出合同

首版沿用 memory_save 和 finish_turn，不新增 frontiers 工具，不增加独立 State／反思调用，也不要求每个 ReAct action 携带一份完整维护 sidecar。

拟议的 finish 输入示例：

```json
{
  "maintenance": {
    "decision": "processed",
    "remaining": [],
    "dispositions": [
      {
        "refs": ["m0"],
        "future_use": "task_local",
        "reason": "该要求仅限定本次回复的排版"
      }
    ]
  },
  "completed_action_refs": [],
  "pending_actions": [],
  "answer": "……"
}
```

dispositions 只覆盖尚未由真实提交或已记录语义处置解释的候选，允许同一理由的准确 refs 分组。程序知道当前 frontier，不让 Host 抄写 UUID、来源 hash、版本号或完整来源清单。没有余项时 dispositions 为空，不产生额外请求。已有 abandoned_attempts 保持其原来含义。

处理规则：

| Host 选择 | 程序检查与结果 |
| --- | --- |
| task_local／none | refs 确实属于当前余项、已交付，理由非空；不覆盖可信 persistence_required |
| cross_turn／durable，尚需新增／修订 | 必须有真实的当前持久写入，或保持 remaining／pending；不能靠填写该值完成保存 |
| 新观察已被既有当前记录表达 | 可用可选 represented_by 指向实际读到的当前 durable 记录，并给简短理由；记录为 Host 的等价判断，不伪称本轮写入或自动增加来源关系 |
| 有一部分尚未处理／必要内容未读 | 列入现有 remaining，状态 pending；不要求为了完成可选判断读完所有长材料 |
| 同一来源已有提交但尚有第二个变化 | Host 必须再处理或留下 remaining；processed 明确承担整体相关语义已处理的声明，程序不替它作证 |

在全局 processed／not_selected 前，不能仍有完全没有处置的候选。拟议错误 FRONTIER_CANDIDATES_UNRESOLVED 只表示“尚未给出合同所需处置”，不表示程序已经判断应该保存。选择需要持久化但没有真实记录时，返回 FRONTIER_DURABLE_CHANGE_NOT_COMMITTED；Host 用正常 memory_save 处理，不自动合成卡。

这会比 v13 多一次明确的剩余语义选择，但不是 v8 的全来源 saved/no_change 报表。是否值得由真实请求数、输出量、错误率判断；若模型仍把首次约定判为 task_local，必须保留为语义失败，不能因新字段合法就通过验收。

### 4.4 生命周期与恢复

候选按真实来源事件去重；重复摄入不重开一份义务。业务等待若已准确保存，则本轮维护可结束；等待的业务动作进入 pending_actions 或卡正文，不滥用 maintenance.remaining。

未处理候选和失败尝试继续进入既有 HostSession.maintenance 快照。processed 前的检查在 preflight 与实际 finish 复用同一函数，前者不得提前清空状态。恢复只继续该 turn 未完成的维护；程序事实相同不制造新业务动作。新会话不能以换 ID 绕过未决状态。

本版不解决任意“来源内多命题”的自动拆分。最小单位是来源／显式事项处置，存在混合消息时依靠 Host 语义判断及诊断，不声称 source_refs 集合覆盖就是全部事实覆盖。

## 5. Action Receipt Grounding：一份执行投影，两层验收

### 5.1 复用已存在的执行事实

business_outcomes 从 RuntimeStore.actions_for_turn 读取 intent/result/reconciliation，补足足够区分事项的信息后，继续放在 semantic_frontier 内。成功、失败与未知都保留。没有 store 的限定运行只能使用同一路径实际得到的 BusinessToolResult，不能从 answer 解析“成功”。

V0 直接使用已有 call_id 作为 action ref，避免另造 aN 执行账本。只投影该次动作名称、状态及必要的直接身份参数；大段消息正文和巨大查询结果使用现有来源展开入口。身份信息超预算时显式省略并保留入口，不能截断标识后当作精确对象。

不在每轮同时交付完整 result、重复 execution summary 和另一份 action state。完整内容仍在原始来源及执行日志中，精简结果只描述它实际证明的范围。可信查询完成不意味着目标业务变化，发送消息也不意味着消息中提到的其他动作已发生。

### 5.2 finish 字段

completed_action_refs 是 Host 在答案中拟作为已完成执行依据的回执引用。程序要求引用真实、属于当前合法上下文、状态为 succeeded；unknown、仅 intent、failed 均不能进入成功集合。合法既往结果必须经当前权限和交付检查显式展开，不因为数据库里存在就自动可用。

pending_actions 是 Host 对尚未完成业务事项的简短表达，标为语义提案；不授权执行、不生成 intent，也不自动把它当作真实世界状态。若已有相应 intent/result，则同时保留真实执行状态。

程序不能凭空断定“manual approval 尚未执行”，因为某个未调用动作甚至可能从未出现在请求或计划中。它能完整列出本轮实际发生的调用；Host 将所需但未发生的动作准确表达为尚未执行。

### 5.3 能保证什么，不能保证什么

可确定性保证：completed_action_refs 中不存在伪造成功，引用“get_order”就只能证明那次查询，真实未决动作不被自动重试。

**不能仅凭该子集检查保证自由文本没有幻觉。** Host 可能提交空 completed_action_refs，仍在 answer 写“审批已完成”。本版不建自然语言完成动词 regex 或审核 Agent；精简事实交付与结构字段是降低这类错误的设计，真实答案是否遵守仍是独立语义检查。

最终 HostResult 应并列保留结构化执行依据、业务未完成说明、原始 answer 和 maintenance 状态。不得根据结构字段改写原生 benchmark 答案或评分。若实际答案仍出现无回执完成声明，G3 为 FAIL，即使所有 JSON 校验通过。

用户面对的完成信息若未来由固定结构摘要渲染，可以减少自由文本对执行状态的支配；这是单独的展示选择，不在本版自动生成“业务全部成功”的模板答案。

## 6. 持久正文校验：引用用途、字面用途与历史污染

### 6.1 校验对象与入口

仅校验本次作者新写入的持久内容，不清洗来源原文，不禁止 task-local 工作笔记使用引用。实际依据由现有 source_refs、source_delta、dependencies 表达，持久文字描述主体、事项、当前状态、未履行事项和范围。

在 Host 已解析引用、尚未提交写入的路径调用一个窄校验函数。CREATE 检查 content；完整 REVISE 检查新 content；content_patch 检查 new 片段，并保留对最终文本中继承问题的独立报告。局部修改不能以“清洁正文”为由替换未交付旧内容。

如果同一普通维护入口可以提交局部 ChangeSet，也必须将其中的新正文送入相同函数；不能只保护最常见分支。原始 RETAIN_SOURCE 及可信来源发布不适用该规则。程序不能改写历史成“从未出现过临时引用”。

### 6.2 实际分配集合不是正则模式

引用 token 集合来自当前 MaterialView／会话实际发布的结构字段。只检测这些完整、区分大小写的标记，不按 mN/rN/cN/pN 外形遍历任意正文。普通路径未发布 cN 或 pN 时，不把它们加入禁用集合。

当前可见授权仍由 HostSession.refresh_visibility 决定。如果需要记住已经交付、后被移出 transcript 的 token 以发现旧指代，只保留已发布 token 名称的轻量集合，放在现有会话维护状态中；它不能恢复可读权限，也不保存被删除正文。优先从现有结构交付记录取得，不能再存一份来源／范围账本。

匹配边界区分 m4 与 m40、M4、文件名中的长标识。中文相邻文字也要能识别，不能直接依赖把中文一律视为同一英文单词的边界规则。引用出现在引号或代码块中并不自动安全：它仍可能是“根据 `m4`”的协议指代。

### 6.3 字面碰撞的最小例外

本版优先保留现有短引用编码，增加仅在碰撞时使用的可选 literal_uses，避免为了这一问题重写全部材料命名。拟议示例：

```json
{
  "op": "CREATE",
  "content": "该设备的型号是 m4。",
  "source_refs": ["m2"],
  "literal_uses": [{"token": "m4", "source_ref": "m2"}]
}
```

例子省略普通 CREATE 其余必需字段。程序只接受已发布 token，且对应字面值真实出现在合法、已交付的原始内容范围中；其 source_ref 必须进入本次有效依据关系。不能拿材料包装器刚生成的 ref 字段、工具 schema、Host 自己的拟写正文或未读来源作字面证明。Host 不手工计算字符偏移，使用现有可见范围确定字符是否已交付。

这是 **Host 声明字面用途＋程序验证字符出处**，不证明任意上下文都在正确谈论型号。若同一文字同时含字面 m4 和“见 m4”的引用用途，仍需改写后者，诊断要检查这一情况。没有声明时返回 PERSISTENT_BODY_CONTAINS_EPHEMERAL_HANDLE；伪造字面出处返回 LITERAL_USE_NOT_GROUNDED，不自动替换、删除或放宽 source visibility。

拒绝回执给出冲突 token 和可行动说明，复用 v13 的失败尝试及 repair_of；合理字面值保留路径必须同样可用。额外拒绝与修复调用计入成本，不能把所有碰撞都叫“成功拦截错误”。如果该例外在真实诊断中过于繁琐或易混淆，应否决当前方案，再单独比较保留字面转义的专用引用编码；不能偷偷扩大拒绝词表。

### 6.4 合同边界

| 场景 | 预期 |
| --- | --- |
| 新正文用实际分配 m4 指向本轮材料 | 拒绝，改成可独立理解的事项说明，引用留结构字段 |
| 原文真实型号 m4，当前也分配了 m4 | 明确字面用途并核对已交付出处后允许；不得改成别的型号 |
| 只存在 m4 绑定，正文写 m40 或 M4 | 不因模糊匹配拒绝 |
| 某个 rN 从未由当前协议发布 | 不凭外形宣判；自由文本正确性另看语义 |
| patch 引入协议 token | 提交前拒绝，无部分修改 |
| patch 未改旧污染片段 | 标记 inherited_prose_issue；不静默改旧文，也不称整卡已清洁 |
| token 被逐出上下文 | 不能再授权 source read；若保留 token 名称，仅用于发现正文指代 |
| 来源／权限撤回或删除 | 保留现有清理合同，字面例外不能绕过 |

“持久正文无协议指代”是语义要求，不是“正文不能出现任何 m 加数字”。机械测试证明有限词法与出处合同，真实诊断验证模型是否仍把字面例外当作藏引用的途径。

### 6.5 更好的默认文字

材料显示既有 about、subject、context、来源角色与准确业务标识。可用的事项锚点应来自实际已取得字段或卡当前正文，不能把另一个模型生成的标题冒充来源事实。没有可靠标题时，显示简短原文摘录和展开入口即可。

持久卡建议表达“事项＋当前状态＋未履行要求＋范围”，但不强制每卡填四个新字段。例如“订单 X 已约定返还某金额，等待用户进一步指令后执行”可同时体现未来价值与未执行状态。历史变更由来源和版本承担；若存在有意义的冲突或历史查询，不能以“只写当前状态”为由删掉必要限制。

## 7. 固定合同优化：先定位，再收敛

现有 _compact_tool_descriptions 已共享相同 schema 的字段，且 v13 只在真实失败存在时返回 repair_guidance。保留这些能力，不再新增等价的 catalogue 或 repair 层。

开发时先用冻结请求离线清点：system shared rules、tool purpose、字段说明、response format、动态 frontier、执行摘要、引用元数据和历史正文。分别标出哪些实际进入 tokenizer、哪些只是本地 JSON schema 配置；不能把未进入模型的 schema 字节算成 prompt tokens。

优化顺序：

1. 同一语义规则只保留一个权威位置，尤其是未来用途、引用用途、业务状态及维护终结说明。
2. 固定工具说明与变化的来源／回执集合分开。schema 构建、模型目录和 dispatcher 从同一能力投影产生，避免“schema 隐藏了但 system 仍声称可调用”。
3. 只按真实权限和阶段隐藏操作。无删除权限就不展示删除；无未决失败就不重复修复说明；需要保留的失败／pending 分支不能因追求短而丢掉。
4. 将超长原始结果保留在合法展开路径，默认只交付其已证明的执行状态及必要身份，不强制完整阅读例行长结果才允许结束。

用同一冻结状态、同样可调用能力比较前后表示。语义新增字段与压缩改动分阶段冻结；不能一边改变任务语义、一边把全部 token 变化归因于压缩。

prefix caching 属于服务运行优化。实施时核对实际 vLLM 版本、启动参数和可用指标，已有缓存不算新实现。保持静态前缀稳定，动态内容在后；动态工具集合改变时接受缓存命中可能下降，不能为了命中缓存扩大权限。没有真实测量不报告延迟改善；缓存命中不从逻辑输入 tokens 中扣除。任何服务重启独立安排，不能打断已有运行或更换模型身份。

## 8. 合同版本与代码边界

| 位置 | 最小变化 |
| --- | --- |
| contextual_maintenance.py | 候选／余项投影、dispositions 校验、精简事实与终结状态；同一校验支持 commit=False |
| contextual_host.py | 使用同一 frontier；结束回执字段解析；写入前正文检查；压缩共享说明 |
| contextual_session.py | 如确需新增字段，只承载既有维护中的处置和已发布 token 名称；可见授权不变 |
| contextual_runtime_store.py | 只复用读取及现有会话快照；必要的附加字段按新身份序列化，不改 intent/result 顺序 |
| material_view.py、write_contract.py | 已有事实锚点投影、字面例外合同和小型纯校验；不改变来源内容 |
| profiles、prepare、runner | 新 ordinary 配置和协议校验，原生数据／工具／评分不变 |
| 现有 trace／报告汇总 | 新字段成本、剩余处置、回执与正文问题分类；不另建分析平台 |

拟定 maintenance v5，独立 contextual-task-v14 notes 模板。write contract 因 literal_uses 等参数变化记录新版本；材料投影若改变其公开合同也记录新版本。仅 finish／工具参数变化不必重造 JSON action 顶层结构，但所有实际 schema 都进入冻结身份及部署解码检查。

旧 v13 配置和制品保持封存。新 runtime identity 不匹配时不能静默读取旧状态当作新实验；本版从新运行库开始。使用旧对象进行离线材料诊断时明确标为 read-side diagnostic，不计为新写入协议的结果。不做批量迁移、compatibility fallback 或 Product 改造。

## 9. 验证设计与冻结纪律

### 9.1 无模型窄检查

优先扩展 [现有维护测试](../tests/unit/test_contextual_turn_maintenance.py)、[恢复测试](../tests/unit/test_contextual_runtime_recovery.py)、[材料视图测试](../tests/unit/test_contextual_material_view.py)、[局部 patch 测试](../tests/unit/test_contextual_content_patch.py)、[prepare 测试](../tests/unit/test_contextual_v9_prepare.py) 与 [MERIT adapter 测试](../tests/unit/test_contextual_merit_adapter.py) 中受影响的用例。

只补能证伪合同的检查：未处理候选不能被全局终结吞掉；合法零写入不受罚；一条来源两个事项不被程序自动宣布全覆盖；失败／unknown 回执不能当成功；自由文本错述不会被结构检查误报为已验证；本轮实际句柄、合法同名字面值及 patch；新处置恢复时不重做业务。

新 schema 先做本地表达与解析检查，必要时使用当前部署的窄解码探针，探针真实用量同样入账。只改变文档不跑 pytest/build。没有包移动和依赖变化不跑全量边界套件；实现后只跑受影响静态检查与窄回归，不预设“测试越多越好”的数量目标。

### 9.2 12 个以内的语义诊断

开发完成后形成并冻结独立诊断输入。下表只定义构造维度，不是已经生成或运行的数据。

| 执行时间 | task_local | cross_turn | durable |
| --- | --- | --- | --- |
| now | 当前回复的格式／计算，明确仅此任务 | 现在处理一项工作，下一相关轮需要其结果 | 本次立即生效、后续长期沿用的明确要求 |
| later | 仅在当前回复／当前限定任务稍后处理，不跨界保留 | 未来履行的约定，本次不得执行 | 将来生效的持续规则，保留实际时间／条件 |
| conditional | 仅本次任务的条件分支 | 等明确触发后执行的未履行事项 | 多次任务复用的条件规则，不无条件概括 |

以上 9 个实例覆盖不同事项，不复制当前退款句式。最多增加 3 个控制：明确不保存／none；临时指令与未来约定同消息；真实字面 token 与已分配句柄碰撞。执行依据的成功、失败、unknown、只有消息却无另一业务动作，在上述任务轨迹与确定性检查中覆盖，无需另造大型套件。

每个案例有冻结的输入、允许工具、初始化、预期保留边界、必要事实与禁止误述。评分标签、期望 future_use、gold 和证据定位不进入 Host／TaskTurn.persistence_required。诊断产生的工具世界是可控本地样例，明确不是新增 MERIT 任务或原生 benchmark 成绩。

评分先核对实际记录、重启后可读性及执行日志，再检查自由文本语义。小样本可以人工逐条核对并记录分歧；若使用 LLM Judge，只使用 vLLM 独立请求及预先冻结 rubric，模型输出不是自动真值。不能只用 expected 字符串命中判断语义，也不能在结果出来后重写 rubric。

### 9.3 历史回归与新原生样本

arc0-000 的旧制品可用于确定性接线重放；它不能验证真实 Host 是否改好了语义。新合同在诊断中选定并冻结后，可用该完整原生 arc 做最终默认配置回归，检查已知首次漏存及错述，不以 5/5 为优化目标。

随后才按 prospective rule 选择两个未用于开发的完整 MERIT arcs。现有 v11 清单已暴露 base_seed 1、2，arc0 更已反复开发；不能把它们重新称为 holdout。执行前汇总已知选择和真实曝光记录，选最小尚未暴露 seed，核对完整任务／世界 SHA；不先读题挑“容易出效果”的例子。相同原始 hash 的重复在调用模型前记录并排除，运行失败后不得换题覆盖。

V14 只跑 ordinary 新合同；此步检验底层语义，不比较 State–Attention。未见实例若被用于修复即成为开发输入。报告保持原生分数，并列语义门槛；不替换原生工具、历史或 checker。两条新 arc 仍只是同一生成器的少量实例，不是跨领域泛化。

## 10. 失败分类、指标与成本

每个失败记录 native score、发生环节、最小证据定位、归因置信度以及可并存的标签；不强迫单标签，也不把标签数加成失败题数。

| 类别 | 使用条件 |
| --- | --- |
| MEMORY_MISS | 应在声明边界之后可用的信息缺失，包括首次未来约定漏存 |
| MEMORY_MISUSE | 错主体、错版本、错误范围、过度持久化或协议指代污染；附具体 subtype |
| ACTION_GROUNDING_ERROR | 结构引用伪造成功，或实际回答把计划／消息当成另一动作已执行 |
| POLICY_ACTION_MISMATCH | 公开政策、可用操作与任务要求存在可举证的歧义／冲突；标注观察与推断 |
| BUSINESS_TOOL_ERROR | 工具确实失败或返回错误；区分错误参数、环境错误和未知执行结果 |
| SCORING_MISMATCH | 有独立证据说明 rubric／checker 与合法任务成功定义不一致；不能仅因不同意分数就贴此标签 |

v13 R1 episode 3 的 ACTION_GROUNDING_ERROR 有直接证据；政策／工具边界作为 POLICY_ACTION_MISMATCH 分析，原生失败不改判。R2 没有复现同样的完成误述，不照搬 R1 标签。首次漏存是 MEMORY_MISS，不因首集消息 checker 通过而消失。

最小指标包括：首次保留正确数／应保留项；task-only／none 过度保留数；未处置候选数及原因；已声明跨轮但无真实保存数；结构回执非法数；自由文本无依据完成声明数；新正文协议引用、字面误伤及继承污染数；任务完成、维护完成、native success 分列。

成本继续分列请求数、输入／输出、失败与截断、embedding、必要 Judge；新增 frontier／执行摘要／处置输出／工具合同的本地分段估计单列，并说明不可直接相加的部分。logical tokens、wall time、缓存统计分开，未知用量保留未知。累计预算／复核次数为 null，单请求／单任务容量继续存在；诊断追加需对应明确新问题和源码身份，不重置账本。

## 11. Readiness 与后续研究

G1 首次保留、G2 不过度保留、G3 动作有真实依据、G4 正文自包含必须同时成立；还要完成用户任务，不能靠全存、全拒绝、永远 pending 或不使用记忆换通过。机械检查通过与真实 Host 语义通过分别报告。

如果 schema 可执行而首次约定仍被判 none，v14 仍是 IMPLEMENTED_WITH_OPEN_SEMANTIC_FAILURES。没有自然写入拒绝时不重复开发 repair 模块。诊断或原生验证出现反例时，先定位是候选未交付、Host 选择错误、提交失败还是后续没有使用；只修该断点，不自动扩大模型、prompt 或样本。

有限门槛通过后，再设计新的三臂实验：共享 v14 语义合同的强 Notes、Sparse Basis、Sparse Basis＋Attention。执行回执、权限、恢复与工具信息必须一致，差异只落在所研究的控制机制。此前 ordinary 的历史轨迹不能直接充当这些新臂的 matched baseline。

v14 的 frontier、回执投影和正文校验首先是工程候选，不以增加字段本身认领算法创新。后续仍需证明版本绑定、选择性重核和 gap 取材在可靠的共同底座上具有独立质量／成本价值。

## 12. 本轮交付声明

本轮已完成静态核对和设计文档。未改运行代码、未建立新配置、未生成诊断集或未见 MERIT 数据、未运行 pytest／vLLM／Judge。文档路径与基线散列可检查，但这些检查不能计作 v14 功能验证。历史 v13 结果及其全部费用保持原样。
