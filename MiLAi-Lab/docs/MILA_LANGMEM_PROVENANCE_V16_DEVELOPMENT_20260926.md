---
version: v16.0
date: 2026-09-26
status: COMPLETE_WITH_INSTRUMENTED_BASELINE
development_base_commit: 79b8b22bb496e85afdac496e04a5cde4057c9cae
reference_commit: 46b8a925385e7b38a7111c7c32283af0eb28467e
scope: MiLAi-Lab
method_scope: B1_MODEL_HIDDEN_INSTRUMENTATION_ONLY
---

# v16 来源、版本和交付追踪开发记录

用户已明确要求阅读并执行更新的 [Goal v16](MILA_LANGMEM_PROVENANCE_GOAL_v16.md)。已完整阅读 Goal 与[开发计划](MILA_LANGMEM_V16_DEVELOPMENT_PLAN_20260926.md)，以当前干净基点 `79b8b22` 开始实施，原规划-only 限定已由执行授权取代。范围只包括 B1 的模型不可见追踪，M1/Basis/adoption/recheck/Attention 不在本轮；不改变原 vLLM 设置。

一个 Sol xhigh 统一负责 sidecar、公开 Store 薄代理、原 Agent/Provider/runner 注入与窄验证。root 负责 reference、新 lock/freeze、环境、真实模型请求（并发 1）、费用及报告。Luna high 沿用最终 Git 发布授权，没有常驻审核代理。

## A：reference 和环境

已创建 [v16 reference 清单](../data/manifests/langmem-b1-v16-reference.json)。开发前逐一核对 v15 原 22 份源码、foundation lock、upstream manifest、final-freeze/results、数据身份和封存账本；均一致。旧 lock SHA 为 `e3b98d9ff15030afeb34eb7548edae3571230f1c20db89766ec7b0c5b12c4090`，旧源码映射 `99fba610b55237aa31de8ad7f25312dc65e847d944b44b3bde1cde572b3e5ef9`。

为必要的同输出旧实现对照，在 ignored `artifacts/langmem-provenance/v15-reference-source/` 保存了原 22 文件及 lock、upstream manifest、原窄测试，共 25 文件。旧 lock 字节保持不变；共享源码若改变，由新 B1 lock 绑定，v15 原入口在其固定提交／快照环境复现，不将当前文件改散列后冒充旧实现。

原 v16 计划 SHA `9f84265c40954e8e31a10c17862e2a5eec8a700683f3ffcacfeede54902a3c2a` 已核对，原文不改。原 12 例诊断、rubric 和 arc0/world/source pin 继续复用，不重生成题、不读取新 seeds。

当前 vLLM 容器运行中，实际 image ID 和 command 与 v15 原设置一致；配置证据保存为 ignored `environment-before-development.json`，未改变服务。长期 Store 复用既有隔离 Lab 后端，但正式 B1 使用新 run/arm/user namespace，从空状态开始，不迁入 v15 记忆。真实 DSN 只进入进程环境。

新连续账本为 `artifacts/langmem-provenance/v16-budget.json`，开发初始生成／embedding 均为 0，累计 caps 为 null，每公开消息 12 次尝试和模型并发 1 继续保留。v15 的 108 次生成、71846 known＋4891 unknown 预留＝76737 charged、836 embedding tokens 单独封存，不清零、不混成 v16 费用。

## 当前实施与验收路径

| 工作 | 需要的直接证据 | 当前状态 |
| --- | --- | --- |
| A reference | 原 lock/结果/费用匹配，新身份不覆盖旧结果 | COMPLETE |
| B Observation | 同事件恢复不重复；同文不同事件不合并；仅实际用户/业务观察 | COMPLETE_V0 |
| C Revision | Goal §6 的实际写入/删除/无效/unknown矩阵、冷读历史 | COMPLETE_V0 |
| D SearchDelivery | search→update 仍绑定旧返回版；实际请求包含与未发送分开；审计查询排除 | COMPLETE_V0 |
| E Action/恢复 | 原 journal 合同保持；sidecar 错误不变成模型可见业务错误 | COMPLETE_V0 |
| F/V0 parity | 同响应、原工具/世界、冻结向量下实际 wire 与效果一致；必要持久后端窄检查 | PASS |
| 最终冻结 | 新 B1 lock、B0-control/B1 配置、源码/可见合同/数据身份一致 | FROZEN |
| V1 | 最终 B1 原 12 例／20 会话，从空 namespace 完成并核对追踪 | COMPLETE |
| V2 | 最终 B1 原 arc0 5 集／7 消息，原世界／空记忆 | COMPLETE |
| 结果交接 | 完整失败、coverage、sidecar 成本、连续费用及 GO 判断 | COMPLETE_WITH_INSTRUMENTED_BASELINE |

instrumentation 只记录事实。没有来源参数时 `source_refs=null / UNKNOWN_NOT_DECLARED`，可见材料不等于采用或语义支持。真实参数拒绝不算工具执行；journal complete 不等于业务成功；原始 wire、规范化对象和正文使用各自身份，不将 hash 等同为原发送字节。主 Store 与 SQLite sidecar 不具有跨库原子性，不能靠当前值相同补造不明提交。

## B–E 开发进展

已写入共同 SQLite sidecar、同步 BaseStore 薄代理及 per-tool ContextVar observer；Agent/Provider 默认关闭的注入开始接线。核对实际上游实现后，代理从真正的 PutOp/Delete（value=None）与 SearchOp 取得 ID 和结果，未改 LangMem 工具。未知 ID upsert、正常 null 正文及 tombstone 作为不同事实保存。

定点检查首版代码发现：Put 前附加读取失败被简化成 before=None，会有把未知旧状态认作 insert@1 的风险；先前非 tombstone 对象突然不存在时也不能假定历史链连续。已在相同边界修复，主业务照常交付，缺少可靠见证时标未知。原 Store 内部异常仅凭 ValueError/TypeError 类名不能证明未提交，现按未知处理，参数验证拒绝仍明确零执行。导入搜索结果的正文引用和 request/thread 复合关联也一并补齐。

首条真实 LangGraph＋固定上游工具＋Mock HTTP 链已通过：manage→search→manage，同批搜索绑定返回时 @1，后续更新为 @2；3 次 Provider 请求 completed，4 条工具正文包含关系均 FULL（同一历史回执进入不同请求分别计交付）。首批 2 项窄检查通过；这只是开发中的零模型接线证据，F/V0 全部合同、冷恢复和最终源码验收尚未完成，未发送真实生成或 embedding 请求。

正式 CLI 已提供 prepare/run/query/summary，B0-control 与 B1 使用独立 arm/run 身份，旧 recipe 保持不变。冷恢复核对又发现内存健康标记会在重启后消失，以及预建 request 若直接标 not_sent 会掩盖“已发出、尚未取得完成见证”的窗口；已在当前开发阶段补入持久 unhealthy/pending 核对与 planned_unknown 状态，不让重启消除未决事实。sidecar 的 call key 也改为原业务 journal 相同的序列化和散列算法，能够直接连接原回执。

root 在现有独立 Lab DSN 下执行了 `check_langmem_provenance_store.py`：唯一 `v16-v0-pg-*` namespace，1024 维固定向量、3 个 Mock HTTP 请求，真实 PostgresStore＋上游工具＋Graph。观察到 insert@1、update@2，search 仍返回 @1、score=1.0，当前正文 soba。证据为 ignored `v0-pg.json`；附加 Store get 共 4 次，sidecar 净增长 12288 bytes。没有真实生成或 embedding 请求。

随后新进程通过只读 query 读取 sidecar，并用公共 PostgresStore.get 核对当前值：历史 ramen/soba 均可从 body_ref 恢复，搜索绑定仍为 @1，当前 Store 为 soba，来源仍 UNKNOWN_NOT_DECLARED。证据 `v0-pg-cold.json`。该已通过后端路径不重复运行；其余版本边界和同输出 parity 继续在固定响应的窄检查中完成。

已完成整条原 v15 MERIT 回放（ignored `v0-v15-merit-replay-r3/report.json`）：21 个真实保留的模型回执、5 个 embedding 返回、原 pinned native world 与业务函数；固定 UUID／时钟只用于 V0。B0-control 与 B1 的实际 HTTPX request.read() UTF-8 请求分别 21/21、5/5 完全相同，请求对象、ToolMessage、5 集结果、世界与 checkpoint 均一致。首版回放因 LangChain 随机 message.id 暴露差异，固定测试内 ID 后通过；失败证据保留。r2 仅证明对象相等，r3 才直接核对原发送字节，未把 JSON 对象 hash 当成 wire hash。

正式入口现在将 request 保存为原 trace 路径、byte offset、整条 trace 记录 SHA 和规范化 request 对象 SHA，不在 sidecar 重复整份请求；离线 V0 缺少受管 trace 才自持 request_json。原 12 例／20 会话及 arc0／5 集／7 消息的开发锁 prepare 已在零模型环境跑通。正式 B1 和 B0-control 新 namespace 已由无 index 的公共 PostgresStore 查询确认空，未触发 embedding。

## 最终冻结与 V0 交接

原 foundation 8 项与新增 10 项合计 18 项窄测试通过，覆盖版本效果矩阵、同文不同事件、search→update 顺序、业务重交付／未知、主写后 sidecar 失败与冷恢复、未取得 Provider 回执的 planned_unknown、参数验证拒绝、imported／外部断链、引用请求恢复与篡改检出。相关 ruff、11 文件 mypy、默认包 99 文件 mypy、active/tools boundary、uv lock --check 均通过。检查记录 `v0-final-checks.json`；无需全套旧测试或全量 benchmark。

新 [B1 lock](../data/locks/langmem-b1.lock.json) SHA `2098f2708081e1ae23341a301356543cb81e3b2be5fe1614ba487647ac8231a7`，27 文件 mapping `ae089f8a1583bf4ef730b0415f4ebd782a722c72398d47ca93af4da9a7d6caea`。原 22 个路径加新 5 个 runtime 路径一起绑定，6 个验证／CI 文件另列。新 [final freeze](../data/manifests/langmem-b1-v16-final-freeze.json) 在真实生成数为 0 时封存；B1 diagnostic、B1 MERIT、关闭 observer 的 B0-control 均完成独立 prepare。B0-control 不重复整套真实运行。

由于 sdist 新增 B1 lock，仅执行一次必要 uv build：工作区／sdist 的 27/27 runtime SHA、两份 lock、wheel 源码与声明验证文件一致，未混入 artifacts、凭据或虚拟环境。证据 `v0-package-check.json`。该构建核对最终 runtime 与 lock；后续文档结论更新无需重复打包。

为简化准确冷读，bodies 按类型和内容寻址保存每种短材料一份；Observation、ToolMessage 和请求材料关联共用该正文。它仍额外保存每种公开输入／业务短结果一次，不声称对原 trace/journal 完全零重复；整段 Provider request 通过 trace 引用避免再次复制。这个明确取舍与 SQLite 净字节一起报告，不另建跨文件解析平台。

## 最终 V1/V2 与结项

冻结后的两组运行分别一次完成：diagnostic 12 例／20 会话，34 个生成请求；MERIT 原 arc0 5 集／7 消息，21 个生成请求。语义 7/12、native 4/5、dependent 1/2，未做语义改动或模型重跑。独立核对通过 27 个用户＋12 个业务 Observation、30 个原调用及工具结果、10 个 insert@1、8 次搜索／6 个返回项、55 个实际请求和 62 次材料包含。全部请求静态合同与对应 v15 实际请求一致，来源未知未被自动升级。

MERIT 多出一次将 query 错发 manage_memory 后的正常 null 插入，随后仍凭空保存并实际退款 5000 分；另一订单退款 6595 后仍保留待执行文字。均按事实记录。真实 UPDATE/DELETE/重交付/unknown 自然覆盖为 0。最终新进程 10/10 当前 Store 对象与 sidecar 正文、字段一致，原服务设置／27 文件 SHA／6 验证 SHA／旧参考／计划均未变。

离线报告最初把结构值按裸 JSON 散列，误报 null 正文；按已冻结 typed JSON 合同修正分析器后全部通过。另一次即时只读摘要误用不存在的 terminal_cases 字段，改用原 cases 列表核对。两者均为报告阶段问题，不是正式运行失败，没有因此修改 runtime 或追加模型调用。

v16 连续新费用 55 次生成、37618 input＋2454 output＝40072 known/charged、17 次 embedding／443 tokens，unknown=0、Judge=0。仪器没有专用 LLM/embedding；两库净增长 155648 bytes、记录 546 笔数据＋stats 事务、额外 Store.get 20 次。具体计时范围、所有保留失败及 G0–G6 GO 判断见[最终结果](MILA_LANGMEM_PROVENANCE_V16_RESULTS_20260926.md)。交付仅 B1 可核对基线，不启动后续方法。
