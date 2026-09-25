---
version: v11.0-design
date: 2026-09-25
status: IMPLEMENTED_PENDING_SMALL_VALIDATION
baseline_commit: 6722c5ea3363d33e366bfadad6ae4fcd941a6588
baseline_source_mapping_sha256: 6528ff9c69a567d40afb096e7ecb1c4e81aeafb3bee0c23b4dba20c57f58e9f4
---

# MiLAi Lab v11 详细设计：稀疏 Basis、确定性重核与缺口 Attention

**结论：采纳“更少、更明确、能改变取材的状态”这个方向。下一版应优先消除表达歧义和无效重复，随后检验普通 search 是否真正消费缺口；不增加记忆模块。**

本文是[开发 Goal v11](MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v11.0_20260925.md)的实施设计。基线代码与 R2 证据已离线核对；下文保留设计时的“拟议”表述作为决策记录。B–D 运行接口、模板与准备入口已实现；旧 arc 失败、公共维护说明修复及后缀诊断均已保留。两个新实例的固定三臂比较正在串行运行；源码复核另发现缓存过度失效，待定向修复。[开发记录](CONTEXTUAL_USER_MEMORY_V11_DEVELOPMENT_20260925.md)区分检查、各次源码身份、实际证据和未完成项。

## 1. 当前代码事实、实验事实和推断

### 1.1 已核对的实现

| 位置 | 当前行为 | v11 应改变什么 |
| --- | --- | --- |
| `decision_basis.STATE_DELTA_SCHEMA` | gap 仅为 string，允许空串；Host 可输出 needs_recheck | gap 可空且有明确语义；needs_recheck 不由 Host 直接声明 |
| `decision_basis.bind_delta` | 每个 set 新建对象并 revision+1；重新记录 current_ref 和已交付来源序列 | 分开实质修改、重核确认和完全无变化 |
| `decision_basis.projected` | 每轮提供协议、ID、revision、采用对象、固定说明、观察和原因 | 保留模型作出下一步决定需要的短视图 |
| `ContextualMemory._scan_decision_changes` | 比较准确采用与当前解析结果，记录变化，不改 adopted exact_ref | 保留；不能为了稀疏性改成跟随最新版 |
| `query_context.project_query` | focus=critical_gap 才用 gap+item，显式 query 与该 focus 同时存在会拒绝 | 用一个确定性解析函数实现 explicit > gap > task |
| `ContextualHost.apply_sidecar` | 接受非 null 就持久化并发 accepted；gap/item 变化清读缓存 | 精确区分事件种类，缓存依赖完整有效查询 |
| `ContextualHost` 请求构造 | 同次输出 sidecar 与 action；投影为请求临时增加的一条消息 | 保留单 Host、同次生成；无 Basis 时不重复空投影 |
| `prepare_contextual_v9`／MERIT runner | 固定选择、ID 和 arc/world hash；runner 只接受 arc0-000 | 参数化选择来源，继续严核每次声明的身份 |

当前 JSON-action 的工具定义在 system 文本中提供，生成 schema 另经 response_format 发送。不能未经计量把两者都当成等量模型输入，也不能为压缩删掉必要工具语义。已有引用绑定、删除、业务执行及维护合同继续复用。

### 1.2 本轮离线补充证据

- 当前 47 文件与 R2 源码映射全部匹配；两臂 result／trace／accounting 六份文件的 hash 匹配已提交清单。
- Basis 45 次生成中 18 次 finish_reason=length，均用满 4096 completion tokens、content 为空、reasoning 非空。截断时 prompt 为 7381—14390 tokens，不能描述成已达到 65536 上下文上限。
- 18 次失败共 234437 tokens，占 Basis 总费用 44.3%；Notes 26 次中有 1 次同类截断。请求截断率分别为 40.0% 和约 3.85%。
- 完整可解析输出为 Basis 27 次：24 个 set 提案、3 个 null；其中 23 个 set 被接受。字段接受率不是 Basis 生命周期占用率。
- 24 个 set 提案有 8 对相邻 JSON 字面相同；这包含未提交提案，且文本相同可能对应新的观察确认，需在绑定后进一步区分。
- R2 请求附加的当前决策消息为 87—1022 字符，中位数 678。该消息是可优化项，但这些字符数不足以解释全部 125.11% 费用增长，不能冒充 token 归因。

统计来自旧制品，不新增独立样本。正式结果继续引用[R2 报告](CONTEXTUAL_USER_MEMORY_V10_R2_RESULTS_20260925.md)和[紧凑清单](../data/manifests/contextual-memory-v10-r2-results.json)，不改写旧评分。

### 1.3 审慎修正根因解释

“控制状态过重、经常更新”有结构和轨迹依据；“这些字段直接造成所有截断”没有被识别。当前能确认的是大量请求在产出动作 JSON 前耗尽混合推理预算。减少重复声明、合同和输入是合理干预，具体收益需重新测量。

episode 3（从 0 起）调用 get_order、三次 get_policy（含一次失败）、send_message；其间连续六次截断。末尾 Decision 是 `refund_requires_approval`，不是“审批已提交”；后续发信和最终回答却声称已提交。可确认的是无执行回执的完成声明；不能将它改写为已证明的“错误 State 导致世界状态幻觉”。

## 2. 稀疏状态的语义与生命周期

### 2.1 激活依据

Host 仅为尚未解决、不同答案会改变下一动作的区别维护 Basis。decision 描述工作判断，critical_gap 描述决定分支的具体未知量。无需额外填写分支树、收益分数或长理由；程序也不通过关键词证明语义分歧。

| 情况 | 行为 |
| --- | --- |
| 例行读取，无论背景原因如何都先读同一文件 | 直接 read；无需为解释原因建立 Basis |
| 客户外发要求是否同时约束内部文件，答案会改变修改范围 | 建立 Basis；依据已见材料，保留此 gap |
| 新用户确认已直接解决问题 | 使用确认完成动作；已有 Basis 则同次 clear |
| 还需用户确认，当前无法继续该事项 | 保留具体 gap，Host 标 deferred；不自动搜旧记忆替代用户确认 |
| 新信息需要长期保存，但当前操作很明确 | 普通 CREATE／REVISE；不先创建 Basis |

稀疏激活由同一个 Host 在普通响应中决定，不增加一个“判断是否需要 Basis”的模型阶段。

### 2.2 三种 null 必须区分

| 表达 | 语义 |
| --- | --- |
| `active_decision = None` | 当前没有受监测决策窗口 |
| `state_delta = null` | 不改变已有状态；不自动确认新观察或清除变化 |
| `critical_gap = null` | Host 声明已无行动敏感的信息缺口 |

严格稀疏版本不持久保留 gap=null 的活动摘要。常规解决路径使用 clear；为使合法 JSON null 能自然表达结束，**set 的 gap=null 在完成其余结构与引用校验后规范化为清槽**，与 clear 同一生命周期效果，不增加 revision，也不保留隐藏决策。回执明确记录 `gap_resolved`；不是静默将错误来源吞掉。无现存槽时为 NO_STATE_CHANGE。

这是一项明确协议选择：null gap 不再表示“把完整摘要继续挂着”。模型若仍有范围／有效性上的行动分歧，就应写出这个具体 gap。暂时延期但仍有问题，使用非空 gap + deferred。

### 2.3 清槽后的监测边界

清槽不删除长期 Memory、不关闭真实业务的 pending、不免除持久维护义务。它只停止这项短期判断的依据监测。新 session 仍按原任务合同清槽，不跨 episode 搬运已解决 Basis。

因此，本版不承诺“问题解决后很久，任意旧依据变化仍唤醒同一决策”。若以后要验证这种持续监测，需要另一项明确生命周期设计；本版不通过隐藏 resolved 槽规避稀疏约束。

## 3. 拟议协议与状态所有权

### 3.1 最小 Host delta

仍为 `null | clear | set`，没有 patch，也没有新工具。

```json
{
  "state_delta": {
    "op": "set",
    "decision": "根据受众决定本次文档保留多少说明",
    "scope": {
      "subject_ref": "u0",
      "item": "文档详细程度",
      "context": "本次内部技术文档"
    },
    "adopted_evidence": ["m3"],
    "critical_gap": "客户要求简短是否也适用于内部技术文档？",
    "status": "active"
  },
  "tool": "memory_search",
  "arguments": {}
}
```

这是字段形状示例，u0／m3 必须由实际会话交付，不能硬编码进任务。还未见材料时允许空采用集合，表示尚未采用依据，不为满足字段强迫搜卡。

拟议 gap schema：

```json
{
  "oneOf": [
    {"type": "null"},
    {"type": "string", "minLength": 1, "maxLength": 240}
  ]
}
```

纯空白和独立哨兵 `null`／`none`／`unknown`／`resolved` 不是合法信息需求；规范化后明确报协议错误，不自动解释为 null。这里是有限的空值表示约定，不是 benchmark 禁词或语义分类器。完整问句中的普通单词不受该约定影响。其余长度／采用数量上限先沿用现有合同，不同时进行多维调参。

`status` 的 Host 输入只允许 active／deferred。程序检测格式和引用，不能认证“这个 gap 确实值得问”。无必要的语义状态通过真实行为诊断，不另加审核模型。

### 3.2 单一状态所有权

内部保存 Host 的 active／deferred 意向和程序生成的未确认变化；对外有效状态由程序计算：有待确认原因时为 needs_recheck，否则为 Host 意向。无需让 Host 和程序同时写一份互相覆盖的 needs_recheck 字符串。

| 内容 | 所有者与含义 |
| --- | --- |
| 判断、范围、gap、继续／延期 | Host 的语义选择 |
| exact_ref、spans、hash、真实版本变化 | 程序绑定及检测 |
| needs_recheck | 程序由真实未确认变化推导 |
| 变化后维持／调整判断 | Host 同次 set 或 clear；程序只记实际声明 |
| 已执行业务、成功／失败／未知 | 真实工具与 RuntimeStore，Basis 不可覆盖 |

即使有 needs_recheck，若 Host 当前意向是 deferred，也不自动进行 gap 检索。有效状态用于通知，暂缓意向用于是否适合当前取材；只用一个 status 字符串判断全部行为会再次混淆二者。

### 3.3 变化确认必须对应已呈现的变化

保留 `adopted exact_ref` 与“已核对到哪个 current_ref”两个不同身份。仅有新版本不会自动更换采用；Host 可以在历史问题中继续采用旧版本，但须已看到相应变化通知后再声明保留。

绑定阶段只能确认本次请求实际呈现的变化身份。不能在 set 时无条件调用最新 resolve 并把尚未呈现的变化也记为已核对；预检后才出现的动作结果也不能提前确认。沿用 HostSession／本次请求的交付信息，不新建长期可见性账本。

对于无旧依赖边的新观察，程序只报告实际新交付；Host 判断后果。没有 set／clear 的 null 不推进“已判断”游标；set 保持判断可以记录本次声明的重核，但程序不因此证明全文已审阅。read 完整性和持久维护继续由原合同负责。

## 4. no-op 与 review acknowledgement

### 4.1 先绑定再比较

比较对象为规范化后的 decision、scope、准确采用集合、gap 与 Host 意向。复用现有 subject／材料绑定；忽略字典顺序与相同引用重复，保留原有句柄展示顺序。仅做外层空白等不改变含义的规范化，不对正文使用模型相似度或擅自大小写归一。

短句柄相同不保证实际对象相同；不同短句柄也可能指向同一准确对象和范围。只有完成绑定后才能判断等值。

### 4.2 转移结果

| 结果 | 语义 revision | 可见性／变化游标 | 检索缓存 |
| --- | --- | --- | --- |
| null | 不变 | 不确认新变化 | 仅按真实外部变化失效 |
| 同值 set，无新变化 | 不变，NO_STATE_CHANGE | 不变 | 不失效 |
| 同值 set，明确确认已呈现变化 | 不变，REVIEW_ACKNOWLEDGED | 只确认已交付变化 | 有效 query／材料不变则不失效 |
| 判断、范围、采用、gap 或 Host 意向实质改变 | 增加，STATE_CHANGED | 记录本次实际声明 | 按实际依赖变化失效 |
| clear／合法 null-gap 结束 | 当前槽删除，CLEARED | 不隐藏未决业务 | 仅相关查询状态失效 |

程序触发 needs_recheck 单列 notification 事件，不混入 Host 语义 revision。NO_STATE_CHANGE 仍可有轻量调用记录，但不写一份新的 Basis checkpoint 内容。不要为了缓存命中抑制真实新材料的变化。

测试必须包含：同内容 set 确认一次已交付版本通知后，通知消失、旧采用保持、语义 revision 不变；重复同一确认不会再次增量。纯 no-op 则连确认游标都不动。

## 5. Attention：解析有效查询，而不是要求 Host 再分类

### 5.1 查询合同

`explicit / gap / default` 是**程序返回的实际查询来源**。Host 日常只需决定是否搜索、是否给具体 query。

```text
resolve_search(query, current_decision, attention_enabled, task):
    若 query 有非空内容：使用 query，origin=explicit
    否则若开启 Attention，Basis 尚在，Host 未 defer，且 gap 非空：
        使用 gap + item + 必要的已知 scope anchor，origin=gap
    否则：使用本轮 task question，origin=default
```

首次 active gap 与 needs_recheck 都适用，不要求先发生版本通知。Host 只输出一个普通 search，程序执行一次现有检索；不自动发起额外工具调用或第二轮 LLM 查询生成。

已有 `focus=critical_gap` 可保留为显式请求缺口的兼容入口；v11 对非空 query 一律尊重 query，不因陈旧 focus 覆盖或拒绝精确查询。空 query 且显式 critical_gap 无合法 gap 时仍明确拒绝。普通默认模式缺 gap 则正常使用 task query。无需再增加一个必须填写的三选一字段。

显式 query 即使很短、与 task question 一样，也视为显式选择。程序不猜测它是不是“够具体”，否则又需要一个语义路由器。A0／A1 可通过正常改写 query 获得同样信息，不限制强基线。

### 5.2 Gap 不保证属于 Memory

有行动分歧并不意味着记忆库能解决：订单当前状态应查业务工具，新的用户授权需要澄清。Basis 不自动选择信息源；Host 仍选工具，程序只在已选择 memory_search 且未给 query 时提供焦点。

scope 中未知受众必须保持未知。拼接已有 item/context 只用于检索，不变成经过验证的过滤条件，不将 scope.context 中的推断加入机器条件求值器。无相关命中可以是有效结果，不能据此无限扩大检索或伪造答案。

### 5.3 执行、缓存和记录共用一份投影

在同次 delta 完整预检并应用后计算有效查询；preflight、实际 dispatch、Host 读缓存、expansion 和 trace 应消费同一解析结果。不能分别拼接，然后只在 trace 中显示一个看似正确的 gap。

缓存身份至少受实际 query、实际过滤／预算、有效材料状态影响；gap、item、context 或当前 task question 改变并影响有效查询时，不复用旧结果。已有覆盖失效和权限检查继续有效。沿现有缓存实现窄改，不加第二个检索缓存。

重点补查两条遗漏风险：null sidecar 但程序产生新通知，和同 task 下一条消息改变 default question。仅在 Host set 时清缓存不足以保证这两条路径。反之，纯 no-op 不应无条件清空缓存。

同一焦点无新增材料的重复 search 沿既有重复读取规则处理，不为提高 gap 使用次数而强制新请求。统计同时区分 search_requested、resolved_origin、retrieval_executed、cached，不能只数参数 focus。

## 6. 紧凑投影与输出合同

### 6.1 模型默认看到什么

```text
Decision: 根据受众决定文档详细程度
Scope: u0 / 文档详细程度 / 内部技术材料
Evidence: c0 = m3@3 [已读范围]
Gap: 外发简短要求是否也适用于内部材料？
Status: needs_recheck; c0 当前出现 @4
New observations: m8
```

示例中的 m3／c0 由当前会话程序发布，不要求 Host 抄全局 ID。保留可识别种类、准确版本及范围是否局部的信息；不能用“source”一词掩盖多个不同来源，也不省掉影响当前使用的撤回／更正。

内部继续保存 task_id、decision_id、revision、hash、exact refs、spans、observed version 和事件身份。协议／UUID／固定解释不反复塞入模型投影；无 Basis 时省掉空投影消息。**完整审计数据仍在原存储，紧凑视图不是新的事实层。**

projection 本身当前已是每次请求临时附加，不需要另外实现跨回合 delta 展示。早先 assistant 的 sidecar 仍可能在 transcript 内重复被计入输入；先测其份额，本版不同时重写 transcript 压缩或开启 H5。

### 6.2 提示应短而明确

共享指令保留业务与记忆的真实边界；Basis 增量只说明：有行动分歧才 set、无变化用 null、解决后 clear、只采用实际已见材料、变化由程序提示。无需解释性 State 文本，不要求每个工具步骤填新状态。

压缩公共工具说明必须同步给三臂，并保留动作参数、来源／授权和成功语义。不要只替候选删长合同，再把节省归因于 Basis。Notes 仍可自由记录判断、依据和缺口，不能人为削弱。

## 7. 截断处理与执行事实

### 7.1 先解决已知执行形态

R2 的失败主要表现为动作 JSON 尚未形成便耗尽输出。先固定相同模型、thinking、4096 输出上限与上下文容量，修改稀疏提示／投影／重复表达后再观察，不直接给候选更高上限。

记录 input、completion、finish_reason、Basis 是否存在／大小、可解析动作与否、前后业务阶段及连续失败。工具缺失的截断只能归为“动作未知”；不能把它们都算维护或 State 调用。

现有 VLLMConfig 仅暴露 max_tokens 和 enable_thinking，未接入独立 reasoning budget。不能承诺对同一次混合推理精确限额“只压 State 思考”。若收敛后仍需调整服务推理／输出配置，先核对实际服务能力，建立新运行身份，并对三臂一致变更。它不是本版必需新功能。

不执行截断 JSON 的前半段，不把 reason 文本当动作；失败全部计费并保持原业务未执行事实。保留现有单任务容量，避免把重复截断当成大量有效 ReAct 步骤。

### 7.2 Business claim 的最小边界

程序能校验结构化执行状态是否对应 operation_id／tool receipt，不能可靠审阅任意自然语言断言。当前 RuntimeStore 的真实结果继续作为执行事实来源；Basis 的 active／clear／deferred 与 finish complete 都不能制造审批、退款或保存成功。

复用现有业务结果摘要，使 Host 能清楚区分“建议提交”“工具已提交”“无此执行能力”。如果真实工具不存在，应如实说明未执行部分，不通过 send_message 冒充审批。这个共享提示适用于所有臂，不为 episode 3 增加专用政策、金额规则或审批工具。

离线诊断使用 `decision → chosen tool → receipt → final claim`。若现有结构化结果已充分可见，则把最终误称保留为 Host 语义失败，而不是再建一个语义审查／阻止回答框架。真实 benchmark 的执行检查与原生评分保留。

## 8. 指标定义与可识别性

### 8.1 稀疏性与 churn

不把用户消息轮次、模型请求和执行动作混为一个 turn：

- `request_occupancy`：请求构造时有 Basis 的 generation 请求数／全部 generation 请求数，含截断和失败。
- `action_occupancy`：合法 action／finish 在 sidecar 应用后有 Basis 的次数／全部实际执行 action／finish 次数；同次首次 set 可计入。
- `activation_count`：None→Basis 的次数；`delta_null/set/clear`、accepted、no-op、review ack 分列。
- `decision_churn`：同一 decision_id 的实质修改次数（不含首次创建、程序通知、确认、no-op）／它占用的动作步骤数；分母为 0 时报告 N/A。
- 另外列用户消息、原生 episode 数、Basis 生命周期长度和期末残留，不把很短的稀疏槽误报成长期状态维护。

不设置目标比例。低激活但漏掉关键决策并非成功；高激活也需结合原任务机会解释。

### 8.2 重核与 gap utility

通知、Host 实际检查、检查后的行为分别统计。程序确定采用版本变化，只能证明通知条件成立，不能自动证明这次检查有行为价值。

有独立事件级标签时才算 precision／recall；“检查后动作未改”既可能合理确认，也可能无用。没有原生标签时，固定小样本用离线事件表记录 relevant／irrelevant／unknown，标签依据不进入 Host，报告 unknown 比例及分母。不同臂内生决策不同，优先按同一原生观察事件配对。

gap utility 至少区分：有资格使用 gap → 请求 search → 实际执行 gap query → 取得此前未交付的相关信息 → 被后续动作或修订采用。检索结果引用变化不自动等于有用；维持正确动作也可能是有效核对。未执行检索的缓存回执不能冒充新 gap 搜索。

A1→A2 比较总结果可衡量自动焦点的整体影响；仅观察同一轨迹的“新增材料”不证明是 gap 的反事实收益。有限样本只给计数和案例，不包装精确的泛化概率。

### 8.3 State overhead 的可测部分

| 项 | 计量办法与边界 |
| --- | --- |
| provider 输入／输出／总量 | 以真实 usage 为主账；所有失败只计一次 |
| 当前投影输入 | 用冻结 tokenizer 测请求里的实际投影文本，标为分段估算 |
| State 固定指令／历史 sidecar 输入 | 分别统计，包含每次重传；不只数最后一条投影 |
| state_delta 输出 | 完整合法／拒绝输出中的字段片段做本地估算；截断不可解析记 unknown |
| grammar/schema | 若服务提供可验证用量则记录；否则不臆测独立 token 成本 |
| 推理输出 | 只在服务可得时分列；共享推理不强行分给 State 或业务 |
| 额外请求 | 只标记可追溯的合同拒绝／恢复等原因；其他因果归因 unknown |
| Judge／embedding | 独立账目，不与部署作答费混成一个指标 |

分段 token 在边界处可能不相加等于完整模板总数。用同 tokenizer 的完整请求与去掉某段的编码差，可作为表示负担诊断，但它不是“模型若没有 State 会节省多少推理”的因果估计。总请求差也不能自动等同于 State-induced calls。

本版不要求把每次截断精确归到一个控制模块。能定位业务／维护阶段、控制状态、输出缺失和成本，就比伪造精确责任比例更有用。

## 9. 代码改动与兼容性

| 边界 | 实施安排 |
| --- | --- |
| 类型／纯转移 | 在 decision_basis.py 收敛 gap、Host 意向、程序原因、比较和投影；不新建控制框架 |
| 查询投影 | project_query 或一个相邻纯函数统一 origin 和 effective_query；执行、缓存引用同一结果 |
| Host 接线 | preflight→sidecar→action 顺序不变；终结同样消费；只增加必要事件摘要 |
| 变化监测 | 继续扫描一个决策的小引用集合；来源替换和卡版本变化均可触发，无关变化不触发 |
| 来源／回执 | 复用 MaterialView、HostSession、RuntimeStore，不新建 ledger 或替代业务世界 |
| 测量 | 先在现有 trace 分析入口加纯统计；仅缺失的请求边界数据在 Host emit |
| 准备入口 | 参数化原生选择清单；不复制一个全新评估 runner |

拟议 `decision-basis-v2` 与新的配置／方法身份用于隔离新语义，最终版本号由真实改动确定，不无差别升级写入、删除和材料协议。v10 错误字符串 gap、状态字段与 checkpoint 不能静默转换成“正确生成的 v11 状态”；本版真实实验重新建立空初态，旧制品只读。

同一 v11 合同下恢复须保留准确采用、未确认变化、Host 意向与业务日志；clear 后重启不能重新出现旧槽。已保存成功结果后中断，续接只能维护／回答，不能重做业务。恢复身份仍核对模型、协议和配置，不为了换实验臂绕过检查。

## 10. 未见任务准备与实验协议

### 10.1 当前固定入口需要真实改造

`prepare_contextual_v9.py` 复制旧 selection，检查固定 arc/world；`run_contextual_merit.prepared_inputs` 也拒绝非 arc0-000。新入口必须从显式冻结选择清单加载官方 generate_suite 参数与所选 arc 身份，并逐项验证原生序列与初始世界。

本地 MERIT 官方 checkout 已在位，固定提交 `293933d96b1d1849e1f20d1bb324def5de9ed33f`；本轮只读取生成器接口与现有适配器，不生成新题。v11 沿原生成器准备两个完整未暴露实例，不编辑消息、标签或 checker。先排查历史 exposure 记录，再锁 seed／参数／ID／hash；同 seed 或同 hash 的旧实例不算未见。

选择依据限公开结构、合法到达顺序和预先声明的规则，不先跑哪个臂得分高再决定留哪题。若原生任务只有跨 session 的长期记忆变化，它测试的是 Memory 复用，不能称 active Basis 的版本通知实验。生成器模板复用的局限明确报告。

StateMemBench、其他数据集和第二模型不自动进入本版。未获得官方数据或自然适用窗口时，机制结论保持有限，不改任务造事件。

### 10.2 三臂唯一干预

| 配置 | A0 Notes | A1 Sparse Basis | A2 Sparse Basis + Attention |
| --- | --- | --- | --- |
| profile／旧 State | ordinary／off | 相同 | 相同 |
| 同次 sidecar | work_note | state_delta | 与 A1 相同 |
| 精确采用与程序重核 | 无 Basis | 有 | 与 A1 相同 |
| 自动 gap focus | 关 | 关 | 开 |
| 自主显式 query／业务工具 | 允许 | 允许 | 允许 |
| 模型、预算、维护、来源和恢复 | 共享 | 共享 | 共享 |

两种 Basis 臂使用同一个 schema、稀疏提示、紧凑格式及反馈规则；差异只在无 query 的搜索解析。A0→A1 为整体方法对照，A1→A2 为 Attention 增量。不能同时关闭 A1 的重核、再把 A2 的增益单独叫 Attention 收益。

当前模板中的模型、thinking、上下文、material 预算和单工作流容量先保持相同。运行顺序事先记录并在两个 arc 间平衡；各 arm×arc 独立记忆／业务初态和同样缓存初态，连续费用共同保留，禁止跨臂复用私有模型结果。失败不补为成功，不挑最好的一次。

### 10.3 验证顺序

1. 在既有窄单测中补合同与副作用断言；对变化 schema 使用现有部署 decoder 的零模型编译探针。
2. 离线冻结对象上比较旧／新投影：当前／历史、角色、版本、范围和必要更正保持；计量结构压缩，不生成摘要。
3. 冻结实现，在暴露 R2 arc 做一次 A2 接线回归；出现 gap 或通知与否如实报告。不要求人为触发，之后问题驱动复核不充当独立样本。
4. 稳定后再冻结两个新原生 arc 和三臂，使用未改的原生 checker。所有方法修改必须发生在这次冻结之前。
5. 新题一旦因结果被用于修提示，即转为开发数据；不再用同题重跑证明未见收益。本轮不自动补选更多题。

窄验证合并覆盖：nullable／哨兵、null／clear、no-op／ack、准确 source／card 采用与无关变化、active／deferred 的 gap 路由、显式 query 优先、同参不同有效 query、恢复及已执行业务不重复。优先扩展既有测试，无需每格各造一个文件或全量组合。

## 11. 研究判断与退出范围

潜在贡献收敛为：在真实行动分歧窗口内维护准确依据，用真实变化触发局部重核，并让缺口影响实际取材。稀疏性、依据绑定、gap 查询各自都不足以单独证明创新；这里首先是可检验的改进方案，不主张首次提出。

本版主动舍弃已解决决策的长期监测，换取更低维护负担。若大部分任务没有这样的窗口，强 Notes 与普通 CRUD 很可能更合适；这也是有效研究结果。

工程验收与效果分开：机制接线正确但无真实机会，报告未覆盖；有真实机制但更贵或更差，报告负面／不确定；只有相同新冻结任务中的原生质量与全成本支持，才讨论优势。无论何种结果，不添加第四臂、更多候选或更多题来遮蔽当前解释。

**当前状态为 `IMPLEMENTED_PENDING_SMALL_VALIDATION`：固定六臂比较仍在运行，缓存过度失效待修复，尚未完成工程验收或效果分析。ordinary 默认及 v10 原始证据保持不变。后续修复必须另记源码身份，不将当前冻结比较冒充修复后新版本的未见验证。**
