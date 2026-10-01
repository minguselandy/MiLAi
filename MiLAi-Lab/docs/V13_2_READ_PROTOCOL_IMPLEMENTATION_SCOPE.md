# v13.2 结果快照、有限读取反馈与保存回执通信的实现范围

仅在 Root 发布并精确核对本范围后，由同一 `/root/v13_2_source_resume` 在新隔离树 `v13-2-read-protocol-implementation` 执行。基准 `7511ddf73691cdb75755e774e47a558391aa6aaf`，运行/测试/完整配置原 maps 为 212/389/316；既有所有树 HOLD。Root 会先创建新树并保存实际创建前后身份，再给明确启动消息；Source 不在外部路径创建 recorder。范围只授权 opt-in 实现和有限、全部断网的本地合成控制，不授权真实 cohort、模型 HTTP、新 SDK/服务或全局 ledger。

已核对的原盲设计 `DESIGN.md` SHA `85a17c817ebb5e64597c0e85905b027f787642e5dd0207ccfc7c7ffe0a666d1c` 为方法输入，按[Root 核对说明](V13_2_READ_PROTOCOL_PROPOSAL_ACCEPTANCE.md)保持静态观察/未验证候选边界。Source 只能读本实现范围及其机器范围和自己的原方案，不读 Root 核对说明、PR 正文、发布 proof 或其他实验文档/manifest。

三个因素分别实现、默认 `legacy`：

| 因素 | opt-in 值 | 授权内容 |
|---|---|---|
| A `memory_read_protocol` | `selected_snapshot_v1` | 将实际 ordinary/explicit 返回的 cursor 解析到其真实不可变快照；原检索、排名、selected 身份和次序保持。 |
| B `tool_read_feedback` | `typed_read_v1` | 在原有限读取 guard 的实际生产点生成 typed 拒绝，由只读工具 facade 忠实返回 error ToolMessage；不改判定条件。 |
| C `tool_save_communication` | `completed_receipt_v1` | 对共同 Host/实际基线/M/writer 给出实际能力适配的保存回执时序说明；不提供其不存在的 Source/revision/CAS 概念。 |

未知值、非法组合、model/builder/service 不一致和实际 freeze/live/resume 漂移须在任何派发前拒绝。A 依赖已存在的 grounded reader、event-bound public Human 与实际读版本合同；无此能力的 native reader 不补造快照/Source/CAS。C 保持独立提示因素，不能宣称保证遵守或修复语义。如果以后共同启用 A+B+C，要按联合机制报告，不归因单一因素。

A 使用实际 `_snapshot/_retrieve/_select/_units/_fit` 的结果，不重新检索。snapshot digest 绑定 owner/bank/namespace、实际 session/turn/Human ref/role/hash、trusted config SHA/policy、ordinary/query 身份、原完整选择/menu、source/index/version/observation-member bindings、真实 material budget 和拟交付 prefix/range/omit 的 shape。实际发行 packet SHA 单独存，避免自引用。resolver 在同一 recipe namespace 按 `selected_snapshot:D` exact get，D 与实际 cursor 一致，完整 H/binding 保留。短 key 冲突实际拒绝，不 overwrite；Store.get/put 不是原子 CAS，合作 get/check/put 临界区使用既有 lock 且不能嵌套 service.read。非合作写/跨源事务不宣称闭合。

双 explicit 与 ordinary 同时存在、同 query 再检索、不同 query 同 menu、不同预算/prefix 的结果必须各自可解析。旧快照不因 dirty refresh 变成新的当前结果；旧真实 revision 仅按历史身份可读，旧 CAS 不因此合法。下一 turn、错误 owner/bank/Human/config、缺失/撤销或 integrity 无法确认均 fail closed；Source/role/hash/版本完整性及权限错误继续传播。observation 只核对原已选成员，不扩大原组；selected-unavailable 保持 unavailable。无新的全库扫描、TTL/GC 任务或“库查全”宣称。快照持久增长是已知限制，实际存储计入。

B 只限原 selected-page 未就绪/invalid cursor、history-view 参数组合、history cursor 和 source-boundary cursor 的精确原 guard，及 A 的真实缺失/撤销快照。不能捕捉 ValueError 后按文字前缀分类。`session_for`/权限检查位于表达 helper 之外；保留 call ID/name、status error、ok false、原有限 reason/origin，feedback 整体完整 JSON ≤1024 UTF-8 bytes。无 args/private cursor/owner/stack 或补造 candidate/source。未知程序错误、GraphBubbleUp、owner/config/Source integrity、预算、CAS、freeze、SDK/Store 故障及 history source-not-found 继续原传播。ToolNode 默认 handler、observer 与业务 journal 不修改，同批已完成 actions 保留；无自动 retry、修参或 Command loop。

C 采用原方案的通用说明：只按已经完成的逐项 mutation receipt 陈述其实际效果；raw event/observation、业务成功、no_change/replay、语义 commit 分别说明；Host final 之后的闭合 writer 不能回溯确认此前保存主张。使用实际 catalog/capability，不分类保存关键词、不强制调用、不猜 Source 蕴含、不前移 writer或修改最终文本。native/json_action 的共同 bridge/recipe、Host catalog、ordinary policy 与单次 closed writer 都进入真实冻结和 cost；ordinary 新文本/metadata/reference 同计 2048/max6，whole request 成本另计，Host12/output4096/temp0、writer1/repair0 不变。

机器范围逐项列出 8 个既有运行可改路径、1 个新 contract、2 个新测试路径和有限只读依赖。不修改现有测试/config/docs/fixtures/rubric/scorer，不修改 compact/support_display/read_tools/revision_store、observer/journal、Product/Archive。需要新依赖或精确改动路径时先给 Root 原因，继续独立工作，不自行扩张。配置原件只可 hash；本地合成配置仅在新树 ignored artifacts/pytest basetemp 内创建。禁止真实 ledger/实验输出/benchmark/gold/holdout/future question 内容；禁止将 Root fixture、评分、业务值、case ID 或隐藏依赖加入 runtime/prompt。

允许 exact 受影响包路径的有限 pytest、ruff/mypy、两个现有 Lab boundary 检查和标准库审计；仅在新树，保留所有实际命令/stdout/stderr/rc/失败及完整运行/测试/配置前后 maps 和实际执行 source SHA。固定已有 Python/SDK，不安装升级，不改模型资源，不生成真实 HTTP；Python bytecode/pytest/cache 输出留在新树或关闭写入，pytest basetemp 明确在新树。所有机制控制先装 socket-denial，MockTransport 和临时预算为本地脚本控制，不能称模型/真实 SDK 质量样本。现有 6 工程测试只读，复用其有限合成 helper；不能执行会读取真实配置/fixtures/ledger 的分支。外部库仅限现有 pinned SDK 和本地 tokenizer 的必要进口/资源读取；自动依赖进口不授权人工展开未列文件内容，必要时提出精确依赖。

拟验收：双结果/重复query/同menu不同prefix、dirty/version/source/member 完整性、同turn实际 reopen 与 wrong-scope/config/撤销/冲突拒绝；真实共享 ToolNode+observer/journal 下先业务 success 后 typed 坏读及独立未知/预算/权限/CAS/freeze 传播；默认 absent/legacy 在 native/json_action×bridge/recipe 的 catalog/参数/wire/grammar/receipts 原字节；Host commit/final/writer pending/partial/unknown 时序及真实 D0/P5 start/resume/freeze；所有因素单独/合法组合/漂移；本地实际 Qwen tokenizer 的短/多语言长 Source、history/backlinks、冲突组和大 metadata 在 prefetch/no-prefetch/显式页下 2048/6 与 whole wire 成本。逐项报告 selected/delivered/full/prefix/omitted、Source/current/history 来源和选择保持，不以总 token 掩盖省略。

交接：精确允许路径的一个源码 commit（不 push），原 HANDOFF、file-index/manifest/source-checks、所有失败/修正前后版本和有限最终验证回执；另列未闭合/未运行能力。完成后 READY/HOLD，Root 独立核对、review diff、执行必要工程检查并另发布接受；下一实际 cohort 仍须 Root 新配置/输入/执行冻结和 GitHub 核对，原 R7 不重跑。全局 HTTP owner 闭包仍是独立未完成要求，不用本次合作 snapshot lock 代替。完整计划 ACTIVE、D4 NOT_ADMITTED、Product NO_GO。
