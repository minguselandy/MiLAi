# v12 S2：通用记忆服务

状态：本地工程验证完成，远端 CI 与发布待完成。迁移前提交为
`02dfacdc75eab478c0d4a49f9765c82073dd7929`，语义实验保持暂停。

三项通用实现从 baseline 层进入 `memory/mcp.py`、`memory/strict_tools.py` 和
`memory/revision_store.py`。为解除 MCP → Agent 的隐藏依赖，精确读取工厂独立为
`memory/read_tools.py`；共享的 `FoundationScope` 下沉至 `contracts/scope.py`。
Agent 保留 recipe、提示和工具组装。旧路径导出 canonical 对象，不增加运行策略。

首个结构断点是 MCP 为复用读取工具而加载整个 Agent 配方。解释一是读取行为本身依赖配方；
解释二是通用读取工厂只是放错层。实际工厂只使用 namespace、Store 和公开工具合同，支持
解释二，因此只迁移工厂，避免整体搬动 Agent。外部 SDK 共用的 scope 同样不需要加载 Agent。

## 冻结合同比较

[合成 golden](../data/diagnostics/code-architecture-v12/memory-contract-golden.json)
来自迁移前真实工厂、InMemoryStore、RevisionSidecar、业务 world/journal/recovery。
UUID、Store 时间、SQLite 时间和计时函数只在捕获 fixture 中固定；生产实现没有这些替换。

捕获包括 36 项同步/异步 strict CRUD 与错误、8 项 MCP 调用及分页/只读/作用域/不自动重试，
还包含版本记录、SQLite schema、重开、业务工具 schema/回执、journal JSON 和丢失回执后的真实查询恢复。
MCP 捕获使用进程内绑定，不能冒称它验证了真实 HTTP；现有短时 loopback HTTP 测试另计。

迁移前和首次迁移后的完整 JSON 均为 191,286 bytes，SHA256 相同：
`76f543e29026f8d9c62fa402b09ed24a942f89ef21952e443b7aba8e09517aae`。
这一证据仅证明合成合同保持，不证明长期记忆正文正确或现实任务已完成。

首次迁移后 Ruff 暴露了移动后导入排序和未使用导入；mypy 暴露了旧 facade 的公开导入符号
需要在 canonical 模块中显式导出。修复限于导入/导出，不改变函数体。一次诊断日志标签被
后续命令覆盖，原失败文本从已显示的工具输出恢复并注明来源，不冒称保留了原始日志文件；
后续 recorder 增加了防覆盖保护。打包验证 driver 曾出现 str/Path 类型错误；只恢复尚未
执行的 Foundation 安装验证，未重复已成功的构建。

当前已通过 23 项合同/结构/source identity 检查、22 项原有机械检查，包含真实 MCP loopback。
Ruff、Core mypy 32 文件、Foundation 显式 mypy 63 文件与 discovery 143 文件、两项 boundary 和 verification matrix 通过。
12 个迁移定义在仅移除 MCP 的局部 Agent 导入后 AST 一致；其余 Agent 配方定义保持。
离线 sdist → wheel 与隔离安装通过：16 个 Core 请求渲染及五类 Foundation 合同重放一致，
所有加载的 `milai_lab` 模块均核对来自新安装目录。复用了已有 Foundation 依赖目录，未安装
或下载新依赖。

sdist SHA256：`81fa2140d9d809fe6706c9f5ba6a42c2fe0556890fd830a2af766c5fd8a5384e`。
wheel SHA256：`4a8421f6ab110b377e6514f298f923f8b2c94689bfc5852b2859a02ee16ceaf2`。
这两项是本次构建身份，不作为后续独立构建字节一致的承诺。

原报告、冻结锁、连续账本、错误记忆和服务配置保留。后续外部集成、benchmark 生命周期、
Provider 策略解耦及最终 CI 仍按[v12 执行记录](CODE_ARCHITECTURE_V12_EXECUTION.md)推进。

精简命令结果、源码身份和初次失败见[工程证据](../data/diagnostics/code-architecture-v12/s2-engineering-evidence.json)。
