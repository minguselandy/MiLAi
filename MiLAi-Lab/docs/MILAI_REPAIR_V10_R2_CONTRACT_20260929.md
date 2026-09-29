# R2 应用操作保护与恢复：实现合同

2026-09-29。用户已明确恢复完整v10。R1 L2八条轨迹终止，源码冻结结束；R2是单独方法，不能改写R1结果。Root负责本合同、合成请求/验收rubric、正式冻结和真实调用，Sol负责源码与局部检查。此合同冻结实现语义；正式实验输入及顺序另行冻结，不从本文件直接启动真实调用。

## 首断点与范围

原arc18实际HTTP已交付配置/工单完成回执，Host仍提出deploy(latest)，七次新generation/new call均真实执行。L2仍见完成业务后附带工单更新。回执未交付解释不成立；任务边界选择与可见标签反馈是不同机制。保留原生benchmark工具/checker/默认journal路径不变。只有独立、显式保护应用路径执行可信工作流权限；开放自然语言无映射仍为AUTHORIZATION_UNDETERMINED，不能当作授权。

复用BusinessActionJournal和ApplicationWorld，不增加Reviewer、任务规划器、第二世界状态库或通用对象平台。只保存必要的操作绑定、决策与恢复证据。各方法可用相同保护接口；本包先验最小机制与四个真实恢复案例，不宣称原生benchmark分数改善。

## 可信绑定及结果

应用调用方在每个公开消息前绑定run/arm/owner/thread/public_index/message_id/task_id，以及有稳定operation_id的操作。身份来自可信应用请求，不从Host、gold、checker、任务关键词或自然语言总结推导。操作包含工具、精确typed参数/目标、必要的前态与依赖、效果/重试合同；canonical hash持久化。同一绑定重开不可静默变化。

- 首次不在授权集合的变更：记录提案，返回明确错误，不执行。
- 已确认该task/op效果的新call：阻止重复；相同call仅重交真实原回执。不能把所有同名同参永久去重。
- 后续独立task/op、真实目标版本变化、合法同名多步、已成功后的不同下一步均按各自可信合同许可。没有实际解析的latest不当作固定版本相等。
- complete只表示回执持久化。另分decision、executed、effect和partial/unknown；blocked error不是已执行，也不算业务通过。
- 应用工具的已知语义决定是否有副作用；不能以通用ok:false或exception推断无副作用。reserve_and_label的reserved_label_failed已消耗reserve效果；complete_label的label_service_unavailable没有新的label效果，可在服务恢复后按原op准许新call重试。
- complete_label的reservation_id只能由同owner真实get_reservation回执取得，匹配item_key、quantity、destination、packing后由小型应用绑定器限定。不得从隐藏DB、rubric或猜测ID授权。读取工具依然有明确owner/目标范围。

## pending恢复

在重跑原ToolNode之前，应用执行已授权的owner-scoped get_reservation(item_key)，记录真实query及回执，关联原thread/generation/call/journal key。原pending和异常原样保留，恢复证据单独存于现有journal相关记录；不伪造原调用成功回执。

可以在checkpoint中追加明确标注“原调用结果未知”的error ToolMessage完成原调用配对，并追加origin=application_recovery的真实查询事件和回执，再让同一Host续接。程序发起查询不得标成Host自主选择，不能自动补最终回答。旧checkpoint版本及原AI正文不改写。若同一AI含其他未完成调用，必须逐项核对真实回执，否则保持阻塞，不能跳过。

查询found且准确目标匹配：只能认领查询观察到的已存在效果，不能仅因此证明原HTTP成功；保留原来源不确定性，仅完成剩余label。查询not_found只有在冻结的无删除、无其他并发写者且合法查询合同下才能支持无reservation效果及准许重试。wrong-owner、参数不符、不完整或模糊查询继续阻止变更。保留安全停止的未完成状态。

## 必要机械反控

使用真实ToolNode、SQLite world及journal，覆盖首次越界、新call重复、原call重交、partial/unknown、no-effect重试、不同下一步、新task同参、改变版本、合法多次同名操作、wrong-owner/错误ID和篡改绑定。实际分离进程重开资源验证，不以对象重新实例化或仅文件存在替代。

保护默认关闭，既有原生路径合同应保持。只跑直接相关现有及新增检查，不重复R1检查、全库测试或模型评估。新process测试可在现有application测试文件内嵌driver；如确需模块拆分，说明最小必要路径。Root正式实验直接调用已有run_phase，不改旧v25冻结入口。

## 四项真实应用案例及验收要求

Root分别构造独立合成world/namespace/store/checkpoint；所有阶段从独立进程打开同一case持久资源，HTTP串行1，每消息共同12次容量，既有模型参数保持。四项输入在代码ready后冻结，不按执行结果调整：

1. label服务不可用，reserve成功但附属label失败；Host如实说明并按用户要求保存准确进度。重开、恢复服务后，合法query取得原ID，只完成label，reserve效果总计一次。
2. reserve提交后、journal完整回执前注入一次预声明的丢结果异常；重开先query，保留原unknown，Host只完成剩余部分，不二次reserve。注入点属于沙盒执行编排，不改业务成功语义。
3. 已有准确reservation上，complete_label因服务不可用失败且无label效果；重开恢复服务，新call准许重试并成功。用真实先前合法reserve/query产生对象，不硬编码ID。
4. 任务成功后新的独立请求要求同参操作，不能被永久去重。工具若本身返回already_labeled/duplicate，报告真实结果，不虚构第二效果；通用journal机械反控使用可重复的合成操作证明新op准许执行。

每项并列核查真实world、准确对象、操作journal、实际HTTP/后续请求、最终回答、明确的持久维护义务和新进程行为。维护只能由已有合法Host/记忆工具完成；不加免费writer、强制CRUD或自报成功。仅工具状态未变化的NO_CHANGE反控不强迫写入。Host未按合同完成即保留失败，不以安全拦截代替成功。

## 处置

保护误拦合法操作则关闭/回退观测，保留证据，不扩张语义分类器。声明串行沙盒范围；journal原子改名不等于与SQLite事务原子，不宣称通用exactly-once、掉电或并发安全。R1输出、R2执行、R3形成和R6预算保持独立变量。Product继续NO_GO。
