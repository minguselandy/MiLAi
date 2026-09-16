# MiLA MCP 0.1.11 本地候选交付包

本包保留普通 Note、统一检索和治理工具，修复作用域提示、Proposal 输入合同、
字段/版本错误及未知写入恢复。普通 Note 无需创建提案或审核，正文原样保存。
模型实验保持暂停。

**这是本地候选包，尚未部署到公网。** 当前 Codex 连接为
`http://36.140.33.19:7968/mcp`（legacy）；另有 OAuth 服务
`https://milai.aigcit.com:7960/mcp`（ordinary）。两者目录不能互相替代，也不能据此包推定已更新。
模型实验继续暂停；工程检查不代表 Agent 自主调用或语义效果通过。

## 安装

包内提供 MCP 0.1.11、Python client 0.1.3、Runtime 0.1.4 的 wheel、源码包和依赖锁。
需要 uv、Python 3.11–3.12，以及依赖下载网络或已有 uv 缓存；不是离线 wheelhouse。

```bash
sha256sum -c SHA256SUMS
sh install.sh /absolute/path/to/new-mcp-venv
sh install.sh /absolute/path/to/new-runtime-venv runtime
/absolute/path/to/new-mcp-venv/bin/milai-codex-full-mcp --help
```

安装仅创建新虚拟环境，不启动服务、修改数据库、更新 OAuth 授权或切换公网程序。
已有 ONNX 部署可用 `MILAI_INSTALL_EMBEDDING=1` 安装可选锁定依赖；此包不含模型。

## 选择工具目录

既有 `milai-codex-full-mcp` 默认仍为 `legacy`，保留原 13 个工具。
完成下述配套升级及服务端授权配置后，启动时显式选择：

```bash
/absolute/path/to/new-mcp-venv/bin/milai-codex-full-mcp --catalog ordinary-memory-v1
```

`ordinary-memory-v1` 包含原 13 个工具、以下 9 个工具及统一入口 `milai_memory_search`，
共 23 个；实际可见性由有效权限交集决定。统一入口需 note.read 或 memory.read，分支各自鉴权。

| 工具 | 用途 | 所需新增 scope |
| --- | --- | --- |
| milai_note_add / milai_note_update | 保存独立笔记 / 追加版本 | milai.note.write |
| milai_note_get / milai_note_list / milai_note_search | 按 ID 读、浏览、搜索 | milai.note.read |
| milai_note_operation_get | 按原操作 ID 确认提交 | milai.note.read |
| milai_note_delete | 删除单条笔记的全部版本可见性 | milai.note.delete |
| milai_evidence_get / milai_evidence_list | 原文回查 / 来源浏览 | milai.evidence.read |

需要新增 scope 时，先核对服务端启用、认证服务许可与当前有效 grant；旧 token 不自动增加权限。
不要仅因目录数量变化就要求重新登录。普通接入不请求用不到的管理 scope。
登录身份与私有项目由服务端绑定，工具不接受模型指定其他用户。修改服务、资源登记和用户
授权属于部署流程，本包不会代办。既有配置示例只包含旧 scope，须按实际部署版本扩展。

## 日常记忆

最小保存：`milai_note_add(content="下次继续需要的信息", operation_id="本次意图的稳定唯一标识")`。
保存后保留回执的 `memory_id`、`version`、`operation_id`。正常成功不必再调用一次 GET。
列表和搜索返回片段及精确回读入口；长正文和来源引用可分别分页，固定返回版本即可继续读。
正文不等于事实，使用时仍由 Host 判断适用性与来源支持。

修改需要当前 `expected_version`；冲突后重新读取并决定如何修改，不静默覆盖。
断线、取消或超时不等于提交失败：先用原 `operation_id` 查询回执；尚无回执也不能证明
仍在途的写入失败。需要重放时使用原 ID 和同一载荷，不换 ID 重写。

删除需要当前用户明确意图及 `confirmation="DELETE"`，只阻断这一条 Note 的全部版本。
当前仅逻辑删除：历史仍保留，主存储物理擦除 `NOT_IMPLEMENTED`，备份到期 `NOT_SCHEDULED`。
删除 Note 不会撤销共享 Evidence、清理命名空间或更改 Canonical。

## 配套升级、迁移与回退

| 组合 | 支持情况 |
| --- | --- |
| MCP 0.1.11 + client 0.1.3 + Runtime 0.1.4 + migration 0056 | 当前修复的候选完整组合 |
| 新 MCP / SDK + 旧 Runtime | 旧能力继续按既有合同；新增方法缺少 capability 时拒绝，不假装兼容 |
| 原 13 工具、Working State、Canonical | 含义不变，原授权继续约束 |
| 回退旧程序但保留新数据库 | 旧程序不能操作 Note；不要为程序回退删除用户记忆 |

本增量无新迁移。若当前数据库尚未达到 `0056_host_notes`，先按既有升级流程核验；
已达 0056 不重复迁移。不要重建身份 namespace/issuer 或覆盖私人数据库。
wheel 内包含迁移资源，可在维护者明确配置目标数据库后使用
`milai.operations.migrations.alembic_config()` 配合 Alembic 执行升级；安装脚本不执行迁移。

0056 仅在 Note 存储为空时允许降级；已有任意 Note（包括逻辑删除的 Note）时明确拒绝。
原文、版本、提交回执和审计应保留，不通过删表实现回退。

完整参数、状态、错误兼容与宿主限制见 `docs/runbooks/mcp-contract-repair-v08.md`、
`contracts/mcp/ordinary-memory-v1.md`。治理高级工具仍保留 Proposal/Review/撤销的明确授权要求。

**Schema 0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE**。
