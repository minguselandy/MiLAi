# MiLAi 检索工具：范围、选择和跨会话查询

适用：本地 MCP `0.1.9` / Runtime `0.1.3` 的 `ordinary-memory-v1` 查询增量；公网是否已更新以实际部署版本及
`tools/list` 为准。OAuth 继续使用[现有接入](aigcit-http-mcp.md)，本改动不重新配置登录。

## 工具方法与覆盖范围

| 需求 | 工具与核心参数 | 查什么 / 不查什么 |
| --- | --- | --- |
| 不知道记忆存在哪一层 | `milai_memory_search(query, note_query?, note_limit?)` | 同时尝试当前授权的 Note 和治理检索；不搜索任务检查点，不全量扫描 Evidence |
| 明确只查普通笔记 | `milai_note_search(query, tags?, limit?, cursor?)` | Note 正文的字面子串；不是自然语言或跨语言语义搜索 |
| 浏览普通笔记 | `milai_note_list(tags?, limit?, cursor?)` | 作用域内稳定分页；不是相关性排序，第一页也不保证是最近记录 |
| 读取笔记全文 | `milai_note_get(memory_id, version?, offset?, length?)` | 指定 Note/版本；长内容按 next_offset 继续，后续页固定版本 |
| 明确检索治理来源 | `milai_memory_resolve(query, previous_context_id?)` | 既有 Evidence/Canonical 候选及资格检查路径；不包含普通 Note |
| 读取正式结论 | `milai_memory_get(claim_id 或 state_key, …)` | 精确 Canonical 读取；不能传入 Note ID/Evidence ID |
| 浏览原始来源 | `milai_evidence_list(source_type?, subject_id?, limit?, cursor?)` | 授权、可读的来源元数据；不读取全部正文 |
| 读取原始来源 | `milai_evidence_get(evidence_id, offset?, length?)` | 按来源自身 ID 读有界正文；不是 Claim 读取 |
| 恢复当前任务检查点 | `milai_working_state_get(scope="TASK")` | 可信绑定范围的检查点；不是全库搜索，ABSENT 不代表没有其他记忆 |

“统一查询”仅统一默认发现入口，不统一数据权威性。Note 仍为 `HOST_WORKING`，Evidence
仍为观察，Canonical 仍受原有治理。已知 ID 时直接调用精确读取工具，不先跑两路搜索。

`milai_note_operation_get` 用于核对提交，Proposal 列表/读取用于治理，删除/清理 status 用于核对
执行状态，均不是历史内容搜索。其他兼容 profile 的 `milai_recall`、`milai_claim_get`、
`milai_evidence_metadata_get`、`milai_trace_get` 等继续保留各自用途，不因此成为新的普通查询入口。

## 默认查询方法

查询主题清楚时可使用：

```json
{"query": "会议"}
```

需要把原问题保留给治理检索时，可明确给出普通笔记的短关键词：

```json
{
  "query": "这周有哪些会议记录？",
  "note_query": "会议",
  "note_limit": 3
}
```

Note 当前按完整 query 字面匹配。把“这周会议 meetings this week”拼成一个字符串，
会要求正文连续包含这一整段，不会自动拆词、翻译或理解时间。
新的统一入口不会在后台偷偷增加模型来改写它；短关键词的选择仍由当前 Host 负责。
词面不同但语义相关的内容仍可能漏检，不能据此宣称跨语言或跨概念召回已经解决。

返回的 `sources.notes` 和 `sources.governed` 分别包含源工具、实际查询、状态和原有结果。
来源独立并发，Note 默认最多 3 条、可配置最多 5 条，治理分支保留已有检索预算；
不自动拉取 50 条笔记、不循环分页、不在搜索时修改记忆。两个内部读取调用均计入成本和日志。

Note 搜索片段现在围绕命中位置返回，而不是总取开头。`snippet_offset/snippet_end`
是原始正文字符位置；`match_in_snippet/match_complete` 区分定位成功与长查询部分呈现。
`snippet_only=true` 仍表示片段，不得把它当全文。否定、条件或日期不完整时按引用精确展开。

## 如何处理未命中

| 状态 | 含义 | 合理后续 |
| --- | --- | --- |
| 顶层 HIT | 至少一类结果存在 | 检查另一分支是否失败，读取相关正文；不代表问题已完整回答 |
| 顶层 MISS | 两个有界查询成功但都未返回匹配 | 改成更短的主题词或进行小页浏览；报告查询范围 |
| 顶层 INCOMPLETE | 无结果且至少一分支未成功查询 | 说明不可用/权限/错误情况，不回答“没有记录” |
| 分支 NOT_AUTHORIZED | 当前身份没有该类读取权限 | 不换身份、不扩大范围、不以登录成功推断全部权限 |
| 分支 UNAVAILABLE / TIMEOUT / ERROR | 本次来源读取未可靠完成 | 保留失败状态；需要时有界重查，不自动遍历其他用户数据 |
| 分支 DEGRADED | 返回结果同时存在降级条件 | 使用已返回合法内容并说明限制，不伪造完整性 |

所有结果的 `absence_confirmed` 都为 false。`BOUNDED_QUERIES_COMPLETED` 仅表示两条
有限查询完成；null cursor 不代表历史不存在。原始来源未索引、关键词不同、预算截断等都可能造成漏检。

合适的表述是“在当前可访问笔记和来源中，按这个查询未找到匹配”，而不是“你没有这段历史”。
必要时只对缺口做一次来源级查询、改写或小页浏览，再明确仍未确认的范围；不要求每次把所有工具调用一遍。

## 跨 session 与时间

同一稳定身份和部署私有空间内，普通 Note 不按 session ID 隔离。新会话通过公开查询或 ID
读取，不应依赖上一轮 Context/cursor 缓存。若仍读不到，核对身份/空间绑定、实际目录和 scopes、
对象类型、删除/来源资格及实际 query；不要首先重建数据库或放宽权限。

`recorded_at` 是记录时间，`observed_at` 也不必然是事件发生时间。今天导入一份旧会议记录，
不能把会议算作今天发生。“这周”按提问时间、用户时区和正文事件日期解释；时区或日期不确定时明确说明。
只有问“这周保存的记录”时，记录时间才是合适的筛选轴。本次没有新增自动日期筛选或会议专用规则。

## 兼容、权限和上线

- 旧 13 工具目录不变；完整 ordinary 目录增加一个只读入口，共 23 项，实际可见项按权限过滤。
- 统一入口接受 `milai.note.read` 或 `milai.memory.read`；每个内部分支仍要求自身 scope。
  获准调用统一入口不意味着获准读取另一类数据，更不获得写入/删除/审核权。
- OAuth 说明与普通目录说明组合，不再覆盖 Note 路由。模型可能缓存旧工具目录和初始化说明，
  部署后应使用新连接核验实际 `initialize` / `tools/list`；本地代码修改不等于现网已变。
- 变更无数据库迁移、不改已保存内容；可回退新增入口而保留旧工具。完整决策见
  [ADR-052](../adr/ADR-052-bounded-cross-type-memory-discovery.md)。
- 工程测试不能证明 Agent 已经正确选择关键词和解释时间；模型实验仍暂停，实际 Agent 验收另行授权。

产品状态保持 `Schema 0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE`。
