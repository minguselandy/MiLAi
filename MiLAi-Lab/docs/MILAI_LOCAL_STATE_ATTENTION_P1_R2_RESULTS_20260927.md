# LSA P1 R2：闭环可运行，语义验收未通过

冻结源码 `bf1ac1f920dd52fb17b6723cb602aae026e43bba`；[R2 协议](../data/manifests/local-state-attention-p1-r2-protocol.json)
继承原两条轨迹、12 消息和 rubric。两个 run 各 phase 0/1 使用独立进程，按预定顺序
串行完成，没有重试、替换样本或修改服务。新 schema 已由真实 decoder 接受，17 次控制
输出和实际 Store 写入无 R1 的标题拒绝；这仅关闭确定性接口缺口。

**任务 strict 为 9/12，完整业务轨迹为 1/2；P1 方法验收未通过。** 所有消息进程均完成，
但错误焦点、未经观察的行动状态和错误业务参数仍存在。不是效果比较，也不是 unseen。

## 实际任务与机制结果

| 轨迹 | strict 消息 | 实际业务世界 | 关键限制 |
| --- | ---: | --- | --- |
| interleaved | 6/6 | 两次预留、数量/地点/包装/key 正确，两个标签完成 | 后台修订时 U=B、A=B，前台 A 靠历史答对；工具执行前 State 已虚构“失败” |
| partial/restart | 3/6 | Mira 原 ID 保留并补完标签，未重复预留；Noel 创建一条错误参数记录 | 两人 key 均把 crates 改为 crate；恢复查询把 reservation ID 当 item_key；Noel 数量/地点错误 |

partial 的两次计划确认与末次门/时间回忆通过。partial-action 因对象 key 变更失败；
restart-recovery 虽用同 ID 成功补标签，但实际读操作 `not_found`，没有完成要求的先读对象；
other-owner-action 数量从 2 变为 1，地点由 `south bay S-8` 变成 `South Bay`，失败。
不能因为最后标签为 created 就将三条记为通过。两用户 State namespace 和业务所有权保持
隔离，没有观察到把 Mira 的数量/ID 送给 Noel；作用域正确不等于参数正确。

部分失败真实回执 `ok=false`、reservation 已提交、label 未完成，确实进入控制 HTTP，
并保存实际 ID 和未完成标签。新进程从 Store 恢复同 ID，未重放预留。最终操作数为
2 reserve + 1 complete_label；这是已验证的持久恢复能力，但不覆盖错误读操作。

原 checkpoint 中 6 个 user/session 的全部公开用户字节与输入一致，没有临时 State
system view 混入原消息。真实工具回执及 tool_call_id 配对在后续 Host 请求中保留。
控制调用与 Host 的计费/request 绑定独立，SER 关闭。没有 controller degraded、截断、
容量失败或残余 pending；本轮没有真实故障注入，零模型恢复检查不能称为真实故障试验。

## 首个断点与竞争解释

Expected：请求执行某操作只改变意图/待办；是否已执行及其结果来自实际观察。
当前读取集合为回答/动作需要的事项，后台更新不应自动替代前台需求。

Observed：interleaved 控制请求 trace 第 22 行在业务调用前写入两份“attempt ... failed”；
partial 的 Noel 行动请求在工具调用前被改写为“attempt made / actual returned ...”，
并把原地点拆成 `South Bay` 与“Identifier: S-8”。这份新 State 被选中、真实原计划未选中。
实际 Host 输入因此已经被污染；其后 Host 又把视图中的数量 2 写成工具参数 1。
Mira 的恢复 State 有真实 ID，但 Host 错将它填入 get_reservation.item_key，并在同批
直接调用 complete_label。工具描述本来已要求完整精确 item key，不能假设多加一次同义
提醒必然修好。

实际链：用户请求 → 控制器推测行动结果/改写事实 → 新 State 写入 → 只选该 State →
Host 错误参数 → 真实错误副作用 → State 又吸收实际错误结果。没有证据表明这是 Postgres
丢数据、模型服务配置变化或 scope 泄漏。

- H1：控制器混淆用户意图与已发生观察，在准备读取时不必要地重写/新建，导致污染。
- H2：focus 更受本批变化或表面主题驱动，遗漏当前所需既有事项；正确 bank 未必交付。
- H3：即使正确参数已在实际请求里，普通 Host 仍可能不遵循或误用工具参数，不能把全部
  行为错误归因于 State。Noel 的数量和 Mira 的读取键为独立线索。

另有两个不能略过的缺口：9 张最终 State 的 evidence_refs 全为空，现有仅按该字段删除
的路径不能证明真实模型产物会被删除；LSA 内部 Store 操作未逐项计量。旧业务 observer
的 extra_store_reads=0 不代表 LSA 零读取。重复的计划/行动卡保留了相互不一致的
“未预留／已预留／标签失败／已完成”描述，未附历史用途标记。

## 最小下一步与决策

**Redesign 局部输入/读取边界，Continue 研究；P3 不启动。** 请临时 Astra 对这一个
已复现的跨层难题提出最小区分设计，由唯一 Sol 收敛实现。优先冻结已有实际 bank/HTTP
的条件使用诊断，比较未改写的原计划、实际污染视图及相同 bank 的读取方式。诊断 Host
输出不执行真实业务副作用，所有控制/Host费用仍计账；正确人工 State 如需使用须单列
oracle，不能混入正常方法成绩。用证据判断先修维护还是读取/Host，不同时堆数个提示补丁。
修复后仍须用原两条完整 development 轨迹验收，不能用诊断成功替代闭环。

删除依赖需机械记录输入血缘且明确不代表事实支持；不靠要求模型自证正确解决。
必要的 Store 计量应为轻量包装，不扩展新的审计平台。完整 P2–P7 目标保持未完成。

## 完整成本与资源

| 轨迹/角色 | 生成 HTTP | generation tokens | HTTP wall seconds |
| --- | ---: | ---: | ---: |
| interleaved / control | 7 | 7083 | 7.491 |
| interleaved / Host | 7 | 7685 | 3.629 |
| partial / control | 10 | 9000 | 10.591 |
| partial / Host | 10 | 10620 | 5.452 |
| 合计 | 34 | 34388 | 27.163 |

另有 1 次 search_memory embedding，9 tokens、0.367 秒；unknown usage=0。
控制共 16083 tokens，Host 共 18305 tokens，前者约占生成量 46.8%。
连续账本为 **903 calls / 1082606 generation tokens / 9626 embedding tokens**。
包括 R1，LSA 至今为 40 次生成 / 39877 generation tokens / 9 embedding tokens。
历史 SER exact-version reads 107 保留，不能与未计量的 LSA bank 读混加。

| 资源 | interleaved | partial |
| --- | ---: | ---: |
| 最终 State 条目 / 逻辑 value UTF-8 字节 | 5 / 1344 | 4 / 1536 |
| 原始 event 条目 / 逻辑 value UTF-8 字节 | 8 / 3758 | 11 / 5108 |
| focus meta 逻辑 value 字节 | 102 | 204 |
| checkpoint SQLite 字节 | 212992 | 258048 |
| instrumentation SQLite 字节 | 98304 | 106496 |
| business-world SQLite 字节 | 36864 | 36864 |
| trace JSONL 字节 | 133868 | 227654 |

逻辑 value 字节按规范紧凑 JSON 计算，不含 Postgres 行、namespace/key、索引/页/WAL
开销，不能当成物理数据库占用。index=False 的 State 写入没有 embedding，现阶段全 bank
读的扩展成本未解决。observer CPU 为 16.83/31.86 ms，wall 为 369.45/561.25 ms；
这些不是所有本地 CPU。调用前 4 次、阶段结束 4 次人工核查 Store search 独立于运行。

ignored 完整证据在 `artifacts/local-state-attention/p1-r2/`，含 execution-freeze、每 run
manifest、两阶段结果、逐阶段 Store 快照、原请求/回执、checkpoint、world/journal、
offline-review 和前后账本。源码及输入哈希由真实入口绑定；R1 原证据不变。
