---
version: v16.0
date: 2026-09-26
status: COMPLETE_WITH_INSTRUMENTED_BASELINE
planning_delivery: COMPLETE
implementation_authorized_this_round: true
scope: MiLAi-Lab
experiment_arm_kind: RESEARCH_PROTOTYPE
method_scope: B1_MODEL_HIDDEN_INSTRUMENTATION_ONLY
reference_commit: 46b8a925385e7b38a7111c7c32283af0eb28467e
reference_source_mapping_sha256: 99fba610b55237aa31de8ad7f25312dc65e847d944b44b3bde1cde572b3e5ef9
reference_foundation_lock_sha256: e3b98d9ff15030afeb34eb7548edae3571230f1c20db89766ec7b0c5b12c4090
development_plan_sha256: 9f84265c40954e8e31a10c17862e2a5eec8a700683f3ffcacfeede54902a3c2a
instrumentation_lock_status: FROZEN
parity_status: PASS_SAME_OUTPUT_RAW_WIRE
model_validation_status: COMPLETE_ORIGINAL_V1_V2
cumulative_generation_request_cap: null
cumulative_generation_token_cap: null
cumulative_embedding_token_cap: null
verification_count_cap: null
---

# v16 开发 Goal：保持 B0 行为的来源、版本与交付追踪

本 Goal 将 [v16 开发计划](MILA_LANGMEM_V16_DEVELOPMENT_PLAN_20260926.md)转成可执行工作包。**本阶段只建立 B1：在已有 LangMem B0 上记录真实观察、记忆版本、搜索交付和业务回执，同时保持模型可见信息、工具语义、检索结果与业务行为不变。**

最初交付仅为 Goal 与导航；用户随后明确要求阅读并执行本 Goal，现已完成 A–F/V0 与最终原范围 V1/V2，状态 COMPLETE_WITH_INSTRUMENTED_BASELINE。文末规划记录保留为历史时点，不限制已授权的工作包。具体能力与边界以[结果报告](MILA_LANGMEM_PROVENANCE_V16_RESULTS_20260926.md)为准。执行范围保持 B1-only，vLLM 服务设置不变。进展见[开发记录](MILA_LANGMEM_PROVENANCE_V16_DEVELOPMENT_20260926.md)。

## 1. 目标与范围收敛

v15 已经完成公共基线接入。v16 不重新建设 foundation，也不修复 B0 的首次约定漏存、凭空写入金额、错误退款或执行后记忆过时；这些行为应能被准确记录，不能被 instrumentation 偷偷阻止或更正。

本阶段的完成条件是：**固定模型输出和工具调用时，B1 的外部可观察行为与 B0 一致；额外出现的是模型不可见、能够恢复核对的事实记录。**真实模型回归检验追踪接线，不以分数提高为目标。

最新 v16 计划比先前 vNext／v15 规划进一步收窄：**M1 Sparse Decision Basis、adopted evidence、自动 recheck、M2 State–Attention 均移到后续独立 Goal。**不因已建立 revision 就提前发版本通知，也不注入更正提示。后续版本编号届时确定，不继续沿用旧规划“v16 同时实现 M1”的范围。

v15 的 JSON-action transport、原 vLLM 服务设置、同一模型和 embedding、上游 manage/search、PostgresStore、SQLite checkpoint、业务 journal、公开任务与原生评分均继续使用。Product、Archive、旧 contextual runtime／frontier／maintenance 不改动。

## 2. 源码核对与 reference 身份

| 项目 | 本轮已核对事实 | v16 处理 |
| --- | --- | --- |
| 当前源码 | 本地 HEAD 为 `46b8a925…`；v15 lock 中 22 份运行文件散列全部匹配 | 固定 B0 reference，历史制品和费用不覆盖 |
| v15 状态 | `COMPLETE_WITH_BASELINE_FAILURES`，foundation GO | 不重跑接入 spike，不把语义全通过作为 B1 前提 |
| 已有结果 | 最终同一源码：12 例／20 会话诊断人工语义 7/12；完整暴露 arc0 native 4/5、dependent 1/2 | 仅作历史行为参照，不是本轮 B1 成绩或未见证据 |
| 已知失败 | 初次约定漏存；无依据 5000 分写入并实际退款；6595 分正确退款后正文仍要求暂不处理；部分记忆未搜索 | 记录机械链及语义诊断，不能增加强制保存／拒绝行动／自动 reconciliation |
| 冻结费用 | 108 次生成；已知输入＋输出 71,846 tokens，另有 4,891 unknown 预留，charged 76,737；embedding 836；Judge=0 | 区分实际已知与预留；v16 另开连续账本 |
| Agent 入口 | `build_agent()` 固定上游工具；已有参数验证、`wrap_tool_call` 与业务 journal 接口 | 在调用边界接入观察，不重写工具或新增语义校验 |
| 模型入口 | `VLLMChatModel._generate()` 生成消息／call ID；现有 Provider trace 保留实际请求和响应 | 复用请求身份与正文，不要求模型填写追踪字段 |
| Store 行为 | 上游允许 null content，unknown-ID update 是 upsert；实际 manage 调用 Store put/delete | 版本依据真实 Store 效果，不能把旧 CAS／目标存在性规则搬进 B1 |
| 运行器 | diagnostic／MERIT 目前硬编码 `b0`；会在会话／episode 后直接枚举 Store 作记录 | 最小化参数化；离线枚举不是 Host search delivery |
| 业务日志 | `BusinessActionJournal` 用 thread／generation／call 识别操作；complete 表示已有结果，pending 为未知 | 沿用恢复合同；complete 不自动等于业务成功 |
| 旧身份校验 | foundation lock 同时核对配方、依赖与 22 份源码 | 保留旧 lock；新源码不能靠改写旧 hash 冒充 v15 |

依据包括 [v15 结果](MILA_LANGMEM_FOUNDATION_V15_RESULTS_20260926.md)、[foundation lock](../data/locks/langmem-foundation.lock.json)、[最终冻结](../data/manifests/langmem-foundation-v15-final-freeze.json)、[Agent 装配](../src/milai_lab/baselines/langmem_agent.py)、[Provider 适配](../src/milai_lab/providers/langmem_chat.py)和[业务 journal](../src/milai_lab/runners/langmem_foundation.py)。本轮为静态核对，没有复跑上述结果。

## 3. 六条执行不变量

1. **Instrumentation 不作策略。**不改变何时写、何时查、是否行动、是否拒答和什么值得保留。
2. **可见、返回、交付、采用分别记录。**在输入中出现不证明支持某张记忆；search 返回不证明进入下一次请求；进入请求不证明模型采用。
3. **版本属于准确对象状态。**使用 namespace＋memory ID＋revision，不仅使用 UUID；不能把旧返回自动绑定到最新 revision。
4. **操作声明不等于实际效果。**工具说 update 可能实际插入；delete 不存在对象可能没有状态变化；业务 complete 回执可能包含失败。
5. **恢复记录不改变重试策略。**重交付已有结果不新增事件；上游若真实重新执行了写入，按实际效果记录，不借 B1 新增记忆幂等或回滚。
6. **不能用追踪失败伪装业务失败。**sidecar 出错要在运行证据中说明，不改变成功的 ToolMessage，也不把额外错误喂给 Host 诱导不同动作。

仅采用当前单进程、单 writer、模型并发 1 的研究范围。无需为未提出的多 writer／分布式事务设计平台；但外部修改造成无法绑定 revision 时必须记 unknown，不能悄悄假定最新值正确。

## 4. 目标数据流和职责

```text
公开用户输入 ──记录真实事件身份──┐
                              ▼
                    原 LangGraph ReAct
                              │
                 原 JSON-action 模型响应
                              │
                 原参数检查和工具调度
                  ┌───────────┼───────────┐
                  ▼           ▼           ▼
             manage_memory search_memory 业务工具／journal
                  │           │           │
             原 Store效果  原搜索结果     原业务结果
                  │           │           │
                  └────模型不可见 sidecar───┘
                              │
                 原 ToolMessage／下一次请求
                              │
                    记录实际请求包含什么
```

sidecar 只保存四类核心对象，以及连接它们所需的 generation／call／request 身份。它不成为第二个检索库，也不参与 embedding、排序、工具 schema 或 prompt。事实记录由程序生成，模型无需再执行工具或输出字段。

## 5. 最小记录合同

### 5.1 ObservationRef：事件身份与内容身份分开

记录 `observation_id、run_id、arm_id、thread_id、session_id、public_message_index、role、actor_ref、artifact、content_sha256、body_ref、observed_at`。完整正文已有受管 trace／journal 时以引用关联，避免每个事件再复制整段 transcript。

- 用户事件来自运行器实际交付的公开输入，稳定身份含会话及消息序号；同一消息恢复不生成新观察。
- 业务结果事件来自实际 ToolMessage／journal 操作身份；重交付同一结果沿用 observation ID，并另记交付次数。
- 相同文字在不同事件出现，content hash 可以相同，event ID 必须不同；不能以正文 hash 去重事件。
- role／actor 由可信运行路径确定，不从正文里的“user said”推断；时间表示记录时间，不伪称偏好的真实生效时间。
- search 的既有记忆、system prompt、tool schema、模型草稿都不注册为新的外部事实来源。评分标签、gold／rubric 不进入 provenance。
- 工具输入验证错误不是业务执行观察；可以记调用失败记录及返回内容，但不伪称外部工具实际执行。

Hash 合同明确到实际内容：字符串使用 UTF-8 原文；结构值采用固定 JSON 序列化并保留类型。空字符串、null 与字符串 `"null"` 不同。原始发送字节、模型 wire-message 和规范化对象的 hash 使用不同字段，不混称字节一致。

### 5.2 MemoryRevision：记录实际写入结果

记录 `namespace、memory_id、revision、operation_id、requested_action、actual_effect、content、content_sha256、source_refs、source_status、recorded_at、supersedes_revision`；必要的 Store created_at／updated_at 原值独立保留。删除版本显式标 `tombstone=true`，不能用 `content=null` 同时表示正常空正文与删除。

上游工具没有 source 参数，默认 `source_refs=null、source_status=UNKNOWN_NOT_DECLARED`。可另存该 generation 实际可见的 observation／delivery 引用，但这些只能叫可见材料，不能命名为语义支持、采用依据或已核实事实。不要把 null 变成表示“已经确认无来源”的空数组。

没有发生语义推断的 sidecar 不会自动知道“5000 分来自何处”。它能显示此前 search 为空、后续 CREATE 正文为 5000、没有显式来源声明；是否为编造由实验分析依据原输入判断，而非 B1 的运行策略。

### 5.3 SearchDelivery：返回与请求包含分别记录

保留 `search_id、generation_id、call_id、thread_id、query、filter、limit、offset、returned_at`；returned 列表按原序保存 `namespace、memory_id、revision、score、content_sha256`。参数同时区分调用中的省略字段和上游实际采用的默认值，不向模型补字段。

每条结果绑定**当次真实返回的版本**，不是之后查询 current 的版本。保存原返回正文 hash／ToolMessage 身份；错误或空结果也是一次 search outcome，返回数量为零，不能从分母中消失。

单独关联 `included_in_requests`：哪些实际 Provider request 包含该 ToolMessage、正文范围是否完整、request 最终是 completed／error／unknown／未发送。capacity 拒绝前就未发出的请求不记为已发送；网络失败只能说明已尝试，不能证明模型实际处理。

因此材料链分为 **Store returned → ToolMessage produced → included in request**；这些都不叫 adopted。v15 当前返回全文时，记录全文即可，不开发新的裁剪视图。只存在 hash 但没有可恢复的准确材料，不能宣称未来已具备依据重读能力。

### 5.4 ActionReceipt：链接既有 journal

复用既有 `thread_id＋generation_id＋call_id` 及 journal key，记录工具名、原参数、journal 状态、ToolMessage 状态、结果正文引用／hash。记清是新执行还是已有结果重交付。

`journal.status=complete` 表示拿到一个结果，不等于 `business_success`。ToolMessage 返回成功也可能携带业务错误 JSON；若原协议没有确定的业务状态，就保留原结果及 unknown。退款回执只证明退了这个金额，不证明金额有用户依据；订单查询成功不表示订单发生了修改。世界变化仅以原生 world before／after或原工具明确定义的效果说明，不从“success”一词猜测。

最终回答不会被解析成新的成功回执，也不触发对任意自然语言的运行时审查。

## 6. MemoryRevision 的边界语义

revision 在每个 `(namespace, memory_id)` 内递增。以下矩阵是实现合同，不改变上游接受／拒绝行为：

| 实际情况 | sidecar 应记录什么 | 不应做什么 |
| --- | --- | --- |
| CREATE 成功写入新 ID | `@1`，requested=create，actual=insert | 不从回执字符串猜 ID；从实际 PutOp／Store操作取得 |
| 已存在对象 UPDATE 成功 | 下一 revision，actual=update，保存实际新正文 | 不追加旧 CAS 或模型可见 expected_version |
| 未知 ID UPDATE 成功 upsert | 首个被观察的 `@1`，requested=update，actual=insert | 不拒绝、不改名为模型提出了 CREATE |
| 同正文 UPDATE 成功 | 仍记录实际成功写操作及下一 revision；标 content_unchanged | 不把真实 Put 静默当无操作；不推断语义已失效 |
| CREATE／UPDATE 的 content 为 null | 正常版本，保留 JSON null 的类型与 hash | 不当作删除、空来源或结构错误 |
| DELETE 确实移除现存对象 | 下一 revision 为 tombstone；旧历史保留在受管 sidecar | 不把删除正文改写为空文本 |
| DELETE 对象本已不存在 | 记录成功调用和 effect=none；不虚构被删除正文或新内容版本 | 不返回新错误；不反复制造 tombstone |
| tombstone 后同 ID 被上游再次 upsert | 在该 ID 已知链上继续递增，actual=recreate／insert | 不从 `@1` 重启并与旧身份冲突 |
| 参数拒绝／明确 Store未提交 | 调用失败，零新 revision | 不把提案内容记成已提交版本 |
| DB／网络结果不明或 sidecar缺失提交见证 | 操作状态 unknown／trace gap；不认领已确认 revision | 不仅凭当前正文相同就推断当初成功 |
| 已有结果被恢复重交付 | 同 operation／revision，另记delivery | 不因第二次显示同回执加一版 |
| 上游实际再次执行了写操作 | 区分 execution attempt，记录真实效果 | 不为维持漂亮版本链偷偷阻止或替换上游操作 |

正式回归从空 B1 namespace 开始，不迁入 v15 的运行库。若为离线 replay 载入既有快照，标明 `snapshot_origin`；缺少历史的现存对象使用 imported／unknown revision 身份，不反推它此前经历了几次修改。没有准确旧版本信息时，future M1 不得将它当已完整追溯的 adoption。

## 7. sidecar 保存、恢复与故障边界

### 7.1 一个小型持久账本即可

建议在本 run ignored 目录内使用单独的 `instrumentation.sqlite`，复用标准库 SQLite 保存事件唯一键、版本链与交付链接。已有 trace／checkpoint／business journal 的正文用引用连接；memory旧版本正文按需保留一次。无需新增数据库服务、向量表、全局图或消息总线。

写入路径采用“记录已进入调用 → 原工具／Store执行 → 记录可确认结果”，在本地事务内提交对应版本和事件，防止 sidecar 内部半条版本链。记录真实 operation attempt；相同完成事件重复落账应幂等，未知调用不靠内容 hash 合并。

**Postgres Store 与本地 sidecar 不构成一个原子事务。**若主写已提交但 sidecar 未完成，应保留待核对状态，不回滚主 Store、不重发 CREATE 来“补齐”、不伪造完成。只有已有可靠执行／提交见证时才离线补关联；当前值恰好相同不足以修复不明窗口。这里不开发通用分布式事务。

### 7.2 追踪错误不能进入模型的业务结果

已核对的 ToolNode 会将一般 wrapper 异常转换成 ToolMessage error。因此 observer内部 I/O错误不能直接穿透该 wrapper，使模型误以为保存或退款失败。

采用一个明确的实验健康状态：保留原工具返回与主操作结果，记录 instrumentation错误；由运行器／请求边界在下一次模型请求前终止该实验臂，结果标 `INSTRUMENTATION_INCOMPLETE`。不能偷偷关闭 sidecar继续宣称 B1完整，也不能把异常改成一句新的模型可见指令。具体实现只需一个窄错误边界，不叠加多层捕获和自动重试。

追踪层故障导致的终止本身不满足完整 parity，必须在报告中作为故障而非正常 B1行为。恢复只能续完可确认的日志／原任务，不能通过新 run ID绕过 pending business动作。

### 7.3 记忆重放与业务重放不同

v15 business journal 已对完整业务结果提供重交付，pending未知不会直接重做；保持该合同。v15 manage_memory没有相同的业务journal保证，不能借 instrumentation给它增加缓存回执、CAS或新的执行幂等。Goal里的“replay不重复revision”指同一已确认事件的日志／结果重交付，不是声称所有崩溃点都能避免上游再次写入。

## 8. 搜索与实际可见性必须按发生顺序绑定

最小反例：同一模型响应依次提出 `search(X) → update(X)`。搜索实际返回 `X@1`，随后 Store变为 `X@2`，下一次请求仍包含先前的 `X@1` 正文。B1应保存 `search→@1` 和 `update→@2`，不能到下一轮按最新 Store查回 `@2`。

再例如 `@1` 和 `@3` 正文相同，只有内容 hash不足以判断搜索返回了哪一次版本。需要真实返回时间的调用顺序与版本索引，不能用正文匹配代替 revision身份。

`runner` 为结果快照调用的 `store.search(namespace, limit=1000)`、checkpoint检查、诊断导出均不是 Host主动搜索。Store observer应根据实际 memory tool调用上下文区分来源，只将真实 `search_memory` 结果记入 Host SearchDelivery；全库快照可作核对，但不能计入可见材料或搜索次数。

结果里的 score、order、namespace、value、created_at／updated_at、原序列化文本原样保留。不得把revision加进memory value／embedding字段，不改返回列表或增加“最新版”标记。B1不为追踪重新跑 embedding、再次执行 semantic search或扩大 top-k。

## 9. 代码落点与最小实现路径

| 位置 | 工作 | 约束 |
| --- | --- | --- |
| 新 `baselines/langmem_instrumentation.py` | 观察者、调用／generation／request关联、纯记录转换 | 不做语义路由，不引入额外工具或LLM |
| 新 `baselines/langmem_revision_store.py` | 本地sidecar、准确版本及事件幂等、只读查询 | 无embedding、无对原Store的语义写入 |
| 既有 `baselines/langmem_agent.py` | 必要时增加默认关闭的窄observer注入，保持原验证／执行顺序 | 优先组合已有wrap_tool_call；不能改变工具签名、描述或结果 |
| 原公共 BaseStore调用边界 | 透明委托实际put/delete/search，取得准确key／结果 | 不fork LangMem；只覆盖当前实际执行的接口，不声称未验证的异步模式 |
| `runners/langmem_foundation.py` | 复用BusinessActionJournal结果；必要的模型不可见链接 | 不改变pending／complete、未知恢复或业务参数 |
| `runners/langmem_merit.py`、`langmem_diagnostic.py` | arm／observer最小参数化，默认B0不变 | 一套循环，无新整份runner；原任务／checker不变 |
| 可选新 `runners/langmem_instrumented.py` | 集中装配sidecar、scope及健康状态 | 仅薄装配；没有第二个Agent循环 |
| `providers/langmem_chat.py` | 优先复用已有message ID／emit；确有需要才加模型不可见hook | 原wire prompt、schema、字段顺序、history渲染和请求容量不变 |
| `baselines/langmem_identity.py`、prepare/run工具 | 新B1／control身份校验和续接；旧入口保留 | 不放宽旧lock、不根据结果切换模式 |
| 新config／lock／manifest／窄测试 | B1开关、sidecar路径、新source freeze、parity结果 | 默认依赖组和服务不升级，私有DSN不提交 |

先用现有工具 wrapper＋Store公开接口薄代理完成，不重造四套模型或额外管理层。当前 ToolNode 即使并发1也在线程执行工具；调用上下文应显式传递或局部绑定，不能使用一个会串call的全局可变“当前generation”。

若合法参数验证在 observer外返回错误，仍可从实际AIMessage／错误ToolMessage记录该attempt；不要为了日志让非法参数进入工具体。修改一个共享机械问题时必须同时适用于B0控制与B1，并新增源码身份，不能混进语义改进。

## 10. A：冻结 reference 和新实验身份

在开始开发时建立 `langmem-b1-v16-reference.json`，引用v15 commit、foundation lock、22文件mapping、final-freeze／results及数据身份。旧 [foundation lock](../data/locks/langmem-foundation.lock.json)字节保持不变，v15复现仍在其固定commit／隔离checkout进行。

对v16确需修改的共享源码，用**新** `data/locks/langmem-b1.lock.json`记录本轮source mapping、instrumentation协议、sidecar格式、arm配置与v15引用。若同一新实现需要运行observer关闭的B0-control，也生成自己的运行freeze；不能拿修改后的文件强行通过旧v15锁。

模型可见recipe ID仍为原 `langmem-hotpath-react-json-action-v1`；在模型不可见的experiment metadata中区分`b0_control`／`b1_instrumented`和instrumentation版本。shared prompt、memory工具schema、JSON-action生成schema、环境规则与依赖hash均纳入parity比较。

实际实验namespace／checkpoint／world／sidecar按arm隔离，不读取另一臂的学习结果。原始diagnostic输入、rubric、MERIT arc／world／source pin引用现有freeze，不重生成题。受管日志中的完整正文和数据库仍保持ignored。

**Gate A：**reference身份可核对，新身份不改写旧结果；当前计划文档与旧结果不存在范围冲突。原v15的M1计划文字作为历史规划保留，本Goal的B1-only范围优先。

## 11. B–E：实现工作包与可验证产物

| 工作包 | 开发任务 | 必须给出的窄证据 |
| --- | --- | --- |
| B：Observation | 在真实用户接入与业务回执处记录身份；连接现有generation／request；区分同文不同事件与恢复 | 重放同事件不新增；不同事件不因hash相同合并；无system/schema/gold注入 |
| C：Revision | Store效果观察＋sidecar；落实§6矩阵；工具参数拒绝、操作失败与未知提交分开 | 实际ID／namespace／正文正确；单调版本；失败零虚构版本；冷启动历史可读 |
| D：SearchDelivery | 捕获原search结果，绑定当时revision；链接实际Provider请求；排除runner审计查询 | 列表／score／内容未改；search后update仍交付旧版本；空／错／未发送可区分 |
| E：Action与恢复 | 关联原journal及Observation；追踪重交付；instrumentation健康边界 | 不重做已完成业务、不重试未知业务；sidecar错误不变成假业务ToolMessage |

四包不各自建账本；共同使用同一小sidecar和既有trace／journal身份。先定义最小事件形状，再逐包增加真实使用点。没有当前用途的字段／索引暂不实现，不能把“以后可能需要”变成整套审计平台。

## 12. F：B0／B1 parity 是主验收

### 12.1 同输出确定性回放

在独立、相同初始状态上，把固定的模型responses、工具calls、embedding向量及世界输入分别交给B0与B1。比较：

- 实际Provider wire messages、response schema、工具定义、历史表示和请求顺序。
- 调用名称、参数、call顺序、工具返回正文／status以及assistant最终文本。
- Store最终值、检索IDs／order／score／content、业务world、journal行为与checkpoint可续接性。
- 生成和embedding请求列表；B1不得额外发请求或重复embedding。sidecar读写耗时／字节另计。

v15现有8项测试作为接线基础，不重复建立大型测试平台。增加少量针对§6边界、search/update顺序、恢复、gold隔离、sidecar故障及真实wire parity的检查；数量不是目标。

### 12.2 随机ID、时间戳与namespace不能成为掩盖差异的借口

主回放使用相同逻辑scope、相同固定UUID／时钟／模型receipt，在隔离Store／checkpoint／world中执行；优先做到模型看到的字节完全一致。测试内固定ID不得进入正式运行，更不能固定benchmark金额或内容。

必要的真实后端比较可以对已声明的独立run namespace／随机ID／时间戳做字段级一一对应核对，但必须单列原始差异，不能全局正则替换正文、忽略排名／分数或删除整个metadata。规范化比较只证明声明范围内的等价，不能写成“请求字节完全一致”。

相同内容重新embedding不一定等于相同检索快照。检索parity应共享冻结向量／数据状态，保留真实后端排序；若后端本身存在tie或浮点差异，要分离后端非确定性与wrapper影响，不为追踪层私自加新tie-break或容差。

### 12.3 真模型回归的正确解释

temperature=0不保证两次运行轨迹逐字相同。B1真实分数与v15历史分数有差异时，先查可见prompt／schema／工具与后端状态；有随机分歧也不能立即归为paritybug。**确定性同输出回放才是因果隔离的主要证据。**

优先利用保留的v15真实trace作零模型重放；必须使用原业务模拟世界／工具实现或明确标注mock，不将只“回放一串预制ToolMessage”当作Store／业务执行parity。缺失制品就说明缺口，不恢复已清理正文或伪造原轨迹。

**Gate F：**同输入／同模型输出的主要路径无非声明可见差异，sidecar完整，开启／关闭不改变请求数或工具语义。存在未解释差异时不进入完整真实B1回归。

## 13. 开发与验证顺序

固定顺序为 **A → B–E实现 → F／V0窄检查 → 最终freeze → V1 → V2 → 结果与GO判断**。基础设施代码先完成，再消耗模型；v16没有重新探索parser的spike阶段。

| 验证包 | 范围 | 用途与退出条件 |
| --- | --- | --- |
| V0 | Observation／revision／search／journal／恢复／wire parity、受影响静态检查 | 零生成；本地后端必要检查使用固定embedding；通过后冻结 |
| V1 | 原v15的12例／20会话，B1单臂，从空namespace运行 | 验证自然trace接线与语义观察；不要求7/12提高，不追加语义修复提示 |
| V2 | 原已暴露MERIT arc0，5集／7消息，B1单臂，原世界／空记忆 | 验证完整业务／搜索／写入轨迹；不要求4/5变5/5 |
| V3 | 未见MERIT seeds3/4、MemSyco fresh选择等 | NOT_RUN；保留到M1／M2冻结之后 |

V1／V2可以在零模型检查定位出的通用机械错误修复后必要复核，但必须新freeze、保留失败及费用；不能把前后源码的成功片段拼成最终整套。若自然轨迹没有UPDATE／DELETE，这两项真实机制覆盖仍是零，只有V0合同证据，不能要求Host为覆盖而更新。

B0真实整套不默认重复运行；使用v15封存结果及同输出离线control。只有parity问题确需新的真实B0来定位时，限定具体问题、共用冻结合同并记全部费用，不扩大为追逐分数的多臂矩阵。

不运行全套旧pytest／全量benchmark。新增模块需要相关boundary检查；默认依赖组／可选组import保持。只有实际打包入口、sdist内容或依赖声明改变才运行一次必要packaging检查。不要为发布重跑模型或已通过检查。

## 14. 统计、失败和成本

| 指标 | 分子／分母及解释 |
| --- | --- |
| Observation coverage | 有效事件ID且可核对内容的用户／业务观察数 ÷ 实际符合定义的事件数；与交付次数分开 |
| Revision coverage | 已确认主Store变化中有准确revision记录的数量；no-effect、failed、unknown各自单列 |
| Search return coverage | 真实Host search调用中已记录参数／状态／原结果的数量，空结果也计入 |
| Request inclusion coverage | 可核对实际Provider请求中的material关联；ToolMessage已生成但未发送不能算已包含 |
| Journal linking | 可连接generation、业务call及原journal结果的数量；complete／failed／unknown／replayed分开 |
| Parity | 原定回放路径、通过数、原始差异、允许的身份差异及未解释差异；不只报告一个PASS |
| Baseline行为 | 原生native／dependent、12例人工语义诊断、writes／searches／business calls；不宣称收益 |
| 仪器成本 | sidecar净增字节、写事务与额外Store读取数、本地CPU／wall耗时；与原日志／Provider等待分开 |
| 模型费用 | 实际生成请求、input／output、embedding、unknown预留；B1应无追踪专用LLM／embedding请求 |

“v15失败可解释”指能核对漏写、空搜索、真实无来源声明的写入和后续业务参数，不等于程序已经判出语义真假或建好因果支持链。source_refs为unknown是保守正确结果，不算为了提高coverage必须补齐的缺陷。

v16使用独立持续账本；累计请求／生成tokens／embeddingtokens／复核次数上限为null，单次输出4096、上下文65536、每公开消息12次实际尝试及并发1沿用既有配置。不得修改vLLM parser、thinking、模型权重、上下文上限或服务容器设置。Provider计一次，observer不重复计费；失败和unknown持续保留。

默认沿用原生checker与人工有限语义复核，Judge=0不是硬性要求；若确有必要使用LLM Judge，只用vLLM、独立评分输入／rubric，费用单列，绝不回写sidecar的“已支持”属性。开发代理费用与实验账本分列。

新的机械失败标 `INSTRUMENTATION_INCOMPLETE、REVISION_BINDING_UNKNOWN、MODEL_VISIBLE_PARITY_MISMATCH、JOURNAL_LINK_MISMATCH`等明确原因；B0原有MEMORY_MISS／MEMORY_MISUSE／ACTION_GROUNDING_ERROR继续作为行为结果。引用有效、回执成功、trace完整均不能替代任务正确性。

## 15. 验收与终态

| Gate | 必须成立 |
| --- | --- |
| G0 身份与范围 | v15参考和费用封存；新B1身份明确；无M1／M2、旧frontier、Product或新seed工作 |
| G1 观察与来源 | 真实事件／内容身份可分；重放不造事件；来源未知不伪装语义支持 |
| G2 版本 | §6实际执行矩阵成立；历史可恢复；无假提交、重绑latest或虚构tombstone |
| G3 交付 | 原搜索内容／顺序／分数未变；返回、ToolMessage和request inclusion可分；无审计查询污染 |
| G4 行动与恢复 | 原journal语义不变；不重复完成业务、不盲目重做未知；sidecar故障不成为假业务错误 |
| G5 Parity | 主要同输出回放通过；原wire schema／prompt／tool行为没有未解释改变 |
| G6 有限真实运行 | 最终源码完成声明的V1／V2，追踪可核对，失败／费用／覆盖缺口完整保留 |

全部必需gate通过，结项 `COMPLETE_WITH_INSTRUMENTED_BASELINE`，可以为后续M1起草独立Goal。`source_refs=unknown`本身不阻止GO；但已声称的revision／delivery存在未知绑定或缺失不能用这个例外放行。

有部分追踪实现但parity或关键覆盖未解决，状态 `COMPLETE_WITH_PARITY_LIMITATIONS`仅表示有限工作交付，**不等于B1准入，不进入M1效果比较**。若必须改变模型可见信息、fork大部LangMem、恢复旧contextual平台才可实现，使用 `STOPPED_FOUNDATION_INSTRUMENTATION_INVALID`，列出原因并转向，不无限扩写。

v16不建立MiLAi方法收益。没有UPDATE、gap或重核的自然事件，不构成这些方法的正／负效果证据。本轮也不因基线分数偏低而增加动作审核或强制拒答。

## 16. 组织、交付与后续接口

常规由一个Sol xhigh负责Agent／Store／sidecar／runner接线及窄测试，避免多人同时修改状态所有权。Luna max可承担锁文件核对、零模型费用汇总或文档等不重叠窄任务；Astra xhigh仅针对实际发生且难以解决的parity／提交窗口问题介入。root统一冻结、请求和连续记账，真实模型并发1；Luna high沿用既有发布授权。没有常驻reviewer或运行时第二模型。

开发交付清单：

- [x] v15 reference清单，新B1配置／lock／source freeze，原模型可见合同hash。
- [x] Observation／Revision／SearchDelivery／ActionReceipt的共同sidecar及窄查询接口。
- [x] 默认关闭的注入、B0-control／B1运行入口、原参数错误与业务恢复合同。
- [x] V0和同输出parity记录，必要真实后端恢复检查，所有不等价差异解释。
- [x] 最终B1的12例旧诊断与完整arc0；原失败、追踪完整性和全部费用。
- [x] `MILA_LANGMEM_PROVENANCE_V16_RESULTS_20260926.md`、复现说明及GO／PIVOT／STOP结论。

后续M1只需要准确的只读查询：某memory准确revision、某observation实际内容、某request真正包含过的材料、后续实际版本变化。v16不输出adopted decision、不修改status为needs_recheck，也不制造用户来源句柄。将来要把短引用给Host时，应在新的matched合同中对B1／M1共享材料外壳，不能倒称那仍是本轮完全model-hidden B1。

## 17. 历史规划记录（实施前时点）

已完整阅读原1192行计划，核对当前v15结果、已安装上游相关实现、LangMem put／delete行为、Agent wrapper、Provider实际wire生成、业务journal、两类runner和原身份锁。计划原文保持不变。

本轮只生成本Goal并更新规划导航、纠正v15仍被标为planned的过期导航状态；v15运行文件／lock／结果不改动。没有安装依赖、修改运行代码、执行测试／模型调用或读取新benchmark题；B1 lock与实验结果仍为NOT_CREATED／NOT_RUN。

## 18. 实施交付记录

用户后续授权执行后，A–F/V0、G0–G6 和最终完整 V1/V2 已完成。新 27 文件 mapping `ae089f8a1583bf4ef730b0415f4ebd782a722c72398d47ca93af4da9a7d6caea`；B1 lock SHA `2098f2708081e1ae23341a301356543cb81e3b2be5fe1614ba487647ac8231a7`。18 项窄测试、同输出 21/21 生成＋5/5 embedding 原请求字节 parity、固定向量 PostgresStore／冷读和一次必要打包通过。

最终原 12 例／20 会话与 arc0／5 集／7 消息均完成，语义 7/12、native 4/5、dependent 1/2；55 个生成请求／40072 tokens、17 个 embedding 请求／443 tokens、unknown=0、Judge=0。39 个外部 Observation、10 次 insert、8 次搜索和 62 次请求材料关联可核对；来源保持 UNKNOWN_NOT_DECLARED。无真实 UPDATE／DELETE；已保留漏写、错误退款和 stale memory，不声称收益。

原 vLLM 设置、v15 lock/结果/费用和 1192 行计划均不变。详见[最终结果](MILA_LANGMEM_PROVENANCE_V16_RESULTS_20260926.md)、[机器清单](../data/manifests/langmem-b1-v16-results.json)及[复现入口](MILA_LANGMEM_PROVENANCE_V16_REPRODUCTION_20260926.md)。M1/Basis/recheck/Attention 与新 seeds 仍未启动，必须另起独立范围。
