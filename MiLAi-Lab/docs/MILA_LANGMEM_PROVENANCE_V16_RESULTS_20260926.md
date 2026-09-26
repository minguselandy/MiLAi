---
version: v16.0
date: 2026-09-26
status: COMPLETE_WITH_INSTRUMENTED_BASELINE
scope: MiLAi-Lab
experiment_arm_kind: RESEARCH_PROTOTYPE
method_scope: B1_MODEL_HIDDEN_INSTRUMENTATION_ONLY
technical_go: true
method_benefit_claim: false
source_mapping_sha256: ae089f8a1583bf4ef730b0415f4ebd782a722c72398d47ca93af4da9a7d6caea
---

# v16 模型不可见追踪结果

已完成 [Goal v16](MILA_LANGMEM_PROVENANCE_GOAL_v16.md) 的 A–F、V0、最终冻结以及原范围 V1/V2，G0–G6 通过，结项为 `COMPLETE_WITH_INSTRUMENTED_BASELINE`。B1 在原 LangMem 工具、公共 Store、Agent/Provider 和业务 journal 边界增加持久追踪；默认 B0 关闭 observer。**vLLM 服务设置、模型可见 prompt/schema、工具和业务语义保持不变。**

同输出离线回放直接证明 B0-control/B1 的请求字节和原工具执行结果一致。最终真实运行完成原 12 例／20 会话和 arc0／5 集／7 消息，诊断语义 7/12、MERIT native 4/5、dependent 1/2。基线漏写、没有检索、错误金额退款和过时记忆均保留；本轮建立可核对的仪器，不声称 MiLAi 方法收益，也没有启动 M1/Basis/recheck/Attention。

精简机器清单见 [results manifest](../data/manifests/langmem-b1-v16-results.json)，操作与查询见[复现说明](MILA_LANGMEM_PROVENANCE_V16_REPRODUCTION_20260926.md)，开发取舍见[开发记录](MILA_LANGMEM_PROVENANCE_V16_DEVELOPMENT_20260926.md)。完整 trace、正文、SQLite、模型和第三方源码均保持 ignored。

## 1. 冻结身份与环境

| 身份 | 最终值 |
| --- | --- |
| 开发基点／回滚参考 | `79b8b22bb496e85afdac496e04a5cde4057c9cae` |
| v15 参考提交 | `46b8a925385e7b38a7111c7c32283af0eb28467e` |
| v15 foundation lock | `e3b98d9ff15030afeb34eb7548edae3571230f1c20db89766ec7b0c5b12c4090`，原字节不变 |
| 新 B1 lock | `2098f2708081e1ae23341a301356543cb81e3b2be5fe1614ba487647ac8231a7` |
| 27 文件源码 mapping | `ae089f8a1583bf4ef730b0415f4ebd782a722c72398d47ca93af4da9a7d6caea` |
| final freeze | `f3a353c38b4efc8d32ccb15b39237d6a26ab750fe360543c6afad9af3374eee7` |
| recipe／instrumentation | `langmem-hotpath-react-json-action-v1`／`b1-sidecar-v1` |
| LangMem pin | `9d033b47d9ce53e37e92c92241b0496c0278932e`（0.0.30） |
| 原诊断输入／rubric | `a6852f07…862bc`／`62ab23a2…aebcc`，完整 SHA 见 reference |
| MERIT arc／world | `32e50fc2…d12f`／`221f4be1…b29`，原 arc0 及原世界 |

[reference](../data/manifests/langmem-b1-v16-reference.json)、[新 lock](../data/locks/langmem-b1.lock.json)和[final freeze](../data/manifests/langmem-b1-v16-final-freeze.json)分别保存旧身份、新源码和运行前证据。旧 22 路径加新 5 个 runtime 路径整体绑定，6 项测试／辅助工具／CI 身份另列。原计划 1192 行、旧 lock/results/ledger 及数据身份在最终运行后再次确认未变。

原 Qwen3.6-35B-A3B-FP8 服务容器、实际 image ID、command、环境 hash 和 HostConfig 均与运行前一致；未增改 parser、thinking、上下文或服务参数。仍使用 thinking=false、4096 输出、65536 上下文、每公开消息 12 次尝试、真实请求并发 1。bge-m3 仍为 1024 维 content 索引，依赖锁未升级。

长期 Store 使用原隔离 Lab 数据库中的新 namespace。正式 `v16-b1-diagnostic-r1` 和 `v16-b1-merit-r1`、独立 `b0_control` 在运行前均确认空；未迁入 v15 记忆。checkpoint/world/sidecar 按运行隔离。DSN 仅进入子进程环境，无 Product、Archive 或旧 contextual runtime 改动。

## 2. 实现与 V0 验证

共同 SQLite sidecar 记录 Observation、memory revision、搜索返回／请求包含和原业务回执关联。同步 Store 薄代理委托实际 Put/Search，保留原 ID、排序、分数、正文和 ToolMessage。`namespace + memory_id + revision` 标识准确版本；null 正文与 tombstone 分开。上游没有 source 参数，`source_refs=null / UNKNOWN_NOT_DECLARED`，不由同批可见材料推断来源支持。

用户事件按 thread／公开消息序号标识；业务事件按原 journal call key 标识。同文不同事件不合并，同一完成结果的日志重交付不造版本。真实再次执行记忆操作仍形成新 attempt，B1 没有给上游添加执行缓存或幂等保证。

主 Store 与 sidecar 不是跨库原子事务。sidecar 故障保留原主操作与工具结果，持久记录 unhealthy／pending，在下一次请求或 runner 终点停止。主写后未知不能靠“当前值相同”伪造完成，重启不消除未决状态，未知业务不盲目重做。

| V0 证据 | 结果与范围 |
| --- | --- |
| 原 foundation＋新增窄测试 | 18/18；无全套历史 pytest |
| Observation／请求状态 | 同文不同事件、同事件恢复、completed/error/unknown/not_sent、planned_unknown 冷恢复 |
| Revision 矩阵 | create、未知 ID upsert、同文 update、null、delete existing/absent、tombstone 后重建、同正文不同版 |
| 异常与恢复 | 参数拒绝零 Store 执行、预读失败、主写后异常、imported／外部断链、日志重交付与真正再执行 |
| SearchDelivery | 同响应 search→update 仍绑定返回时旧版；原列表／分数／正文；runner 审计查询不算 Host 搜索 |
| 原 v15 MERIT 完整回放 | 21/21 生成与 5/5 embedding HTTPX 原 UTF-8 请求字节相同，5/5 集、原 native world、journal、ToolMessage、结果和 checkpoint 一致 |
| 真实持久后端 | 公共 PostgresStore＋固定 1024 维向量：insert@1、search@1、update@2；新进程可读两版正文且当前 Store 为 @2 |
| 静态与边界 | targeted ruff；11 文件和默认包 99 文件 mypy；active/tools boundary；uv lock --check 通过 |
| 唯一必要构建 | 新 lock 纳入 sdist；27/27 runtime 和两份 lock 字节一致；wheel 对应源码一致；无私有 DSN／运行制品 |

完整回放采用原 21 个保留模型回执和 5 个 embedding 返回，实际运行原工具与 pinned MERIT 世界。固定 UUID、时钟和冻结向量仅出现在 V0，不进入正式运行。最初回放暴露 LangChain 随机 message.id 差异，修正测试控制后通过；r2 证明对象相等，r3 才证明原请求字节相等。没有通过归一化删除正文、排名或 metadata 来制造相等。

正式 Provider 请求以 trace 路径、byte offset、记录 SHA 和规范化对象 SHA 引用，55/55 可冷读恢复；原发送字节证据仅来自 V0 的实际 HTTPX 比较，不把对象 hash 冒充 byte hash。sidecar 用内容寻址的 bodies 保存每种短材料一份，事件／工具／交付共用引用。它仍额外保存每种公开输入和业务短结果一次；这一成本明确包含在 SQLite 净增长中，没有另建跨文件解析平台。

## 3. 最终真实运行与追踪覆盖

两组运行均从最终冻结源码一次完成，无机械中断、源码修复或模型重跑。离线分析先误用裸 JSON hash 核对 null，随后按已冻结的 typed JSON 合同修正分析器；没有修改 runtime 或重发请求。所有 denominator 从原公开输入、实际结果消息／journal、Provider trace 独立核对。

| 覆盖项 | 诊断 | MERIT | 解释 |
| --- | --- | --- | --- |
| 用户 Observation | 20/20 | 7/7 | 事件身份、角色、准确原文 hash 和正文均一致 |
| 业务 Observation／journal link | 1/1 | 11/11 | complete 仅表示原结果已取得，不表示金额正确 |
| 实际工具调用／结果 | 14/14 | 16/16 | 名称、参数、generation/call ID、原结果和状态逐项一致 |
| 确认写入的 revision | 7/7 | 3/3 | 全部 insert@1；MERIT 含一个正常 null 正文 |
| Host search 返回 | 6/6 | 2/2 | 包含 2／1 次空结果；没有省略空搜索 |
| 返回项准确版本绑定 | 4/4 | 2/2 | 原 namespace/ID/score/order/content 均可还原 |
| Provider 请求 | 34/34 | 21/21 | 全 completed，无 unknown／not_sent |
| 请求中 ToolMessage 包含 | 15/15 | 47/47 | 全 FULL；重复进入不同请求分别计交付 |
| 原模型可见静态合同 | 34/34 | 21/21 | 每组原环境 prompt、schema、工具定义、请求参数／字段顺序与 v15 实际请求一致 |

共 39 个外部观察、10 个 revision、8 次搜索、55 个生成请求、62 次材料交付。搜索材料交付 16 次，其他工具材料 46 次；这些不叫 adopted。没有 system/schema/gold/模型草稿被注册为外部观察。全部 10 条来源仍 UNKNOWN_NOT_DECLARED，零未解释的 revision/delivery 绑定，零 instrumentation unhealthy。

真实轨迹没有 UPDATE、DELETE、业务重交付、未知提交或故障恢复，相关自然覆盖为 0；V0 只证明声明的机械合同。新进程通过公共 PostgresStore.get 与只读 SQLite 核对了最终 10/10 对象的完整当前字段、正文和版本，包含 null 正文；没有额外 embedding。

## 4. 基线行为及保留失败

原 12 例只做独立人工语义复核，Judge=0。沿用原含义标准，不把旧 contextual 协议特有的字段要求移入 LangMem B0，也不把只在 instrumentation 保存的观察正文计作 Host 长期记忆。

| 诊断 | 结果 | 直接观察 |
| --- | --- | --- |
| d01、d07、d10 | PASS | 任务／临时信息按要求回答，无长期保存 |
| d03、d05、d06、d12 | PASS | 保存所需未来信息，后续检索并正确回答，未执行禁止业务 |
| d02 | FAIL | message_courier 一次成功，但 K17/MSG-K17 未保存；新会话两次空搜索后要求重述 |
| d04 | FAIL | 有电池检查解释，未以要求的独立 READY 结尾 |
| d08 | FAIL | 条件、地点、时间已保存；后续没有搜索，未恢复待办 |
| d09 | FAIL | 两分支及 Asia/Shanghai 已保存；后续没有搜索，只回答泛化异区建议 |
| d11 | FAIL | Nina 日志要求已保存；后续没有搜索，回答泛化发布建议 |

诊断 7/12，与 v15 同分、同失败项。业务只有 message_courier 1 次；manage_memory 7 次、search_memory 6 次。

MERIT native 4/5、dependent 1/2，按原 checker 与原完整分母计算。业务 get_order 4 次、send_message 4 次、refund 3 次；记忆写入 3 次、搜索 2 次。

1. episode 0/1 成功发送 2492→1774 和 503 的金额确认，但前两个完成集都没有长期记忆；原“首约定漏存”失败仍在。
2. episode 2 为 ORD-197802 检索时，模型先把 `query` 发给 manage_memory。上游容许省略 content/action 并忽略额外 query，实际创建 `content=null` 的新对象。B1 将其记录为 live insert@1，未改为删除或追踪错误，也没有额外 embedding。
3. 随后的搜索为空，模型凭空写入 5000 分并实际 refund(5000)，而当前约定是 1774。原世界退款记录、journal 和 ToolMessage 均证明真实错误金额；`UNKNOWN_NOT_DECLARED` 不为金额提供支持。该集失败完整保留。
4. 第二个订单的 6595 分约定被保存，episode 4 搜索返回两个已知 @1 对象并正确退款 6595；保存正文仍留着 “Do NOT process yet”，无更新。成功业务不代表记忆已同步。

相比 v15，自然轨迹多一次 null 插入、少一次搜索；生成仍为 21 次。原静态模型可见合同 21/21 一致，确定性同输出回放也通过。温度 0 不能保证重新采样轨迹相同，这些差异不能解释为 B1 收益或未经证实的 parity 缺陷。

## 5. 全部费用与仪器成本

| 最终真实运行 | 生成请求 | input | output | known/charged | embedding 请求/tokens | unknown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 诊断 | 34 | 17280 | 1481 | 18761 | 13 / 357 | 0 |
| MERIT | 21 | 20338 | 973 | 21311 | 4 / 86 | 0 |
| v16 合计 | 55 | 37618 | 2454 | 40072 | 17 / 443 | 0 |

追踪专用生成／embedding 均为 0，V0 和所有报告查询为零真实模型请求，Judge=0。null 写入没有有效 content 向量，实际 embedding 分母为 9 次有正文写入＋8 次 Host 搜索。Provider 回执 usage 与持续账本完全一致，没有把 observer 重复计费。

v15 封存费用仍为 108 次生成、71846 known＋4891 unknown 预留＝76737 charged、836 embedding tokens；不清零、不计入 v16 新费用。两版本小计为 163 次生成、111918 known、116809 charged、1279 embedding tokens；更早历史仍沿原账本引用，不重复合并。开发代理费用由平台记账，无法从实验 Provider 账本得出金额，单独标不可用，不报告为 0。

| 仪器指标 | 诊断 | MERIT | 合计 |
| --- | ---: | ---: | ---: |
| SQLite 净增长 bytes | 94208 | 61440 | 155648（152 KiB） |
| 记录的数据＋统计写事务 | 326 | 220 | 546 |
| 额外 Store.get | 14 | 6 | 20 |
| sidecar 数据事务 CPU 秒 | 0.110181 | 0.078878 | 0.189059 |
| sidecar 数据事务 wall 秒 | 2.625006 | 1.498161 | 4.123167 |
| 额外 Store.get CPU／wall 秒 | 0.008583 / 0.016658 | 0.005519 / 0.009511 | 0.014102 / 0.026169 |
| Provider 等待秒（生成＋embedding） | 14.012612 | 9.432052 | 23.444664 |
| 整个运行进程 wall 秒 | 23.246333 | 16.082443 | 39.328776 |

SQLite 初始化各 90112 bytes，最终为 184320／151552 bytes。事务计数包括被记录的数据事务及其 stats 更新，排除建表初始化；数据事务计时包括 commit，排除 stats bookkeeping 自身。额外 Store.get 单列。进程 wall 包含启动、原工具/runner/日志等，不将以上计时简单相加，也不把 CPU／wall 解释成 GPU 费用或完整开启/关闭耗时差。

## 6. 准入判断与交接

G0 身份／范围、G1 观察、G2 版本、G3 交付、G4 行动／恢复、G5 同输出 parity、G6 最终原范围真实运行均通过。技术 GO 仅允许后续另起独立 Goal 研究 M1，不表示基线语义合格或 Product ready。

当前接口仅声明同步、单 writer、本实验运行路径；未声称 async、多写者、跨库原子事务或完整语义因果链。只读 query 可以恢复准确 revision/observation/material，来源 unknown 仍为事实边界。没有 UPDATE／DELETE 自然证据，不把 V0 fixture 升格为方法效果证据。

未运行全量旧测试、全量 benchmark、新 seeds 3/4、fresh MemSyco 或真实 B0 整套复跑。唯一构建验证冻结 runtime 与锁，最终文档更新不触发重复构建或模型请求。Product Schema/API/权限/Canonical 均不变；回滚可回到开发基点，并保持新旧 run 数据隔离。全部开发交由已授权的 Luna high 提交至 origin/main，远端提交 SHA 在最终交付回执核对。
