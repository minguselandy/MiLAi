# 普通文件来源：公开导入、隔离和冷恢复

状态：`PUBLIC_FILE_IMPORT_COLD_RECOVERY_AND_REVOCATION_VERIFIED`，0模型调用。
这是来源与Host文件读取的工程证据，不是Agent生成计划、语义续做或正式D4/D5通过。

`v02_file_sources.py`增加`v02-file-source-only-v1`来源包：相对文件路径、原始URI、观察
时间、完整UTF-8内容与hash。正文是不透明文本，不解释Markdown/JSON业务字段。校验非法
路径、路径冲突、重复身份、无时区时间、hash变化和来源包额外字段后才导入；当前公开
文本采集不支持二进制及全空白文件，明确拒绝，不静默删除。

文件观察使用现有公开Hook的TOOL_RESULT，不伪装成用户发言或LME材料。subject_id保留原始
文件URI；source_ref包含项目绑定、原URI摘要及内容版本，以隔离公开导入身份。观察时间是
读取冻结快照的时间，不伪造原文发布日期或最后修改时间。正文逐字节保持，引用只表示
文件依赖，不自动证明每条计划结论被所有来源支持。

`v02_public_snapshot.py`复用同一公开Hook/SDK导入、公开GET核验和三臂绑定逻辑；旧LME
模式不变。新的实际来源仍是四份完整项目文档，总计13,746字节。G/A/B各4条Evidence，
共12条回执；每条核对完整正文、角色、URI、时间、项目、保留状态和显式关系字段。
三臂原始文件hash相同，Evidence ID不同；初始State必须ABSENT，不清空已有内容。

真实运行：

```bash
PYTHONPATH=tools:src .venv/bin/python tools/check_v02_file_snapshot.py --config configs/v02-file-snapshot-engineering.json --root artifacts/v02-e2e-generality/file-snapshot-engineering-20260907a
```

通过公开接口保存三个不同State及读取确认。这里的State明确标为工程fixture，不冒充G
的实际记忆产物。随后退出原客户端，五个独立进程通过公开MCP恢复并使用实际Host
`list_files`/`read_file`分页到EOF，比较原始UTF-8字节：

| 冷进程 | 结果 |
|---|---|
| G/A/B初次恢复 | 各自版本/完整payload正确，四文件全部可发现、完整可读 |
| 撤销A的ADR-042来源后恢复A | State正文隐藏；该文件不出现在发现结果，直接读取拒绝；其他三文件仍完整可读 |
| 撤销后恢复B | B的State及全部四文件仍完整可读，不继承A的写入/撤销 |

没有通过原进程缓存或直接SQL绕过公开接口。此项未运行模型、未评价实际Host请求中的
内容理解，也未覆盖所有文件格式/规模。显式写入为12次Evidence采集、3次State保存、
1次撤销；来源资格GET、就绪和协议往返另外存在，没有将这些写入数当全部服务成本。
实例独占，PG2CPU/1GiB、进程CPU affinity2；不是负载SLO测试。API/worker/MCP及五个冷
进程均退出，PG停止exit0、无OOM，共享服务未改。数据保留。

运行时Product pin保持`cb3edf1226376d5fcb17074f6322fa9b5ed4df3e10e1c10184f7b3abc03c167a`，
采用`v02-blob-write-timing-clarified-product.lock.json`；本轮Product源码不变，无迁移、
权限或Canonical改动，Schema仍NO-GO。

下一条真实规划链也已接到既有coordinator：`v02-file-evaluation-v1`用文件路径＋原URI＋
span hash核对来源判据，续做问题只从独立evaluation文件传给A/B。来源包拒绝混入question
或gold；G的初始文件只包含四份普通文档。旧会话来源评价分支继续保留。
配置`configs/v02-project-planning-development.json`与六项完整判据已冻结并验证；模型发送
关闭、分配0，尚未运行。既有宽松本地开发授权未撤销，正式D3未完成状态也不因配置准备改变。

验证：来源/评价定向31通过，完整Lab417通过（3.81秒）；boundary、Ruff、mypy src（30文件）、
build通过。初始Ruff导入顺序/行长问题已修正。未重跑未变动的Product全套测试；实际PG/公开
Hook/MCP链是本轮直接集成证据。下一步是正常G产物→公开保存→A/B冷续做，不能继续用这份
工程fixture替代模型任务。
