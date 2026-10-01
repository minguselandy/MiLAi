# v13.2 读取协议只读方案范围补充

在原[只读范围](V13_2_READ_PROTOCOL_PROPOSAL_SCOPE.md)与机器范围原件不变的前提下，追加两个真实调用依赖的静态读取权限。Source 已提出具体依赖理由并明确尚未读取；本补充由 Root 发布并核对远端后才开始。仍由既有 `/root/v13_2_source_resume` 在 `v13-2-read-protocol-proposal` 隔离树执行，基准 `da33e6169c2745fbb50aee3f0a4370b9ceb1f02f`，运行/测试/配置完整 map 保持 212/389/316。

- `src/milai_lab/baselines/langmem_instrumentation.py`：静态核对 `ProvenanceObserver.run_tool`、`safe`、`incomplete`、`assert_healthy`、调用上下文定义及直接 helper，确认实际工具异常是否重抛、真实 ToolMessage 的 call ID/status 如何记录，观察器失败如何暴露。文件 SHA `0fea97120ffd1b9a079584aab728c05ed88d0bcb28119355e8629b68f1e32555`。
- `src/milai_lab/application/journal.py`：静态核对 `BusinessActionJournal.__call__`、`entry_for_call`、直接执行/拒绝/异常记录 helper 与必要类型定义，确认读取协议呈现点位于业务记录之外，以及同批已完成 actions 的原回执如何保留。文件 SHA `6b5ab1b478bf00158829e2a22898a04a77928f5812690f6ab0e6dd6c5485dad7`。不修改 journal 行为，不读取任何真实 journal 内容。

允许对这两个精确文件保存字节/hash、rg/AST 和必要静态调用链说明；不扩展到它们 import 的其他文件。若直接 helper 的外部定义无法由已允许文件闭合，应登记未验证依赖并提出精确理由。仍禁止执行源码、pytest、SDK、合成机制、实际模型 HTTP、配置内容、ledger、实验结果、fixtures、rubric、scorer、benchmark/gold/holdout 或未来问题。只读工程观察不能升级为实际行为或质量结论，下一实现仍须单独授权范围。

已发生的外部 bootstrap 写入单独保留：Source 为记录新树 setup 在 `/cra/memory/mx_memory/artifacts/v13-2-read-protocol-proposal-bootstrap` 写了记录器/日志，不符合原“仅新树写入”边界。Root 在获知后只接受保留既有原件、逐字节复制至授权新树和在交接中列明路径/SHA的窄例外。外部原件 HOLD，不新增外部记录，不删除或覆盖，不能把事后例外表述为原先授权。没有当时完整 maps 的恢复上下文读取只保留实际工具输入/响应与缺失标记，不倒补 maps。本补充不预先认可尚未独立审核的交接材料。

[补充机器范围](../data/manifests/v13-2-read-protocol-proposal-scope-addendum.json)保存上述精确身份。原范围、完整计划与历史失败原样保留；Full plan ACTIVE、D4 NOT_ADMITTED、Product NO_GO。
