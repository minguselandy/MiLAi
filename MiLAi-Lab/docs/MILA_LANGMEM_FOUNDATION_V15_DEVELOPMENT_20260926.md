---
version: v15.0
date: 2026-09-26
status: COMPLETE_WITH_BASELINE_FAILURES
planning_commit: 197b75c
reference_commit: 0802d34f49db45bd654fc745d33da3252c0d4e24
scope: MiLAi-Lab
---

# v15 LangMem Foundation 开发记录

用户明确授权执行 [Goal](MILA_LANGMEM_FOUNDATION_GOAL_v15.md)，原规划限定已被取代。已完整阅读 Goal、319 行路线图和适用仓库规则，按 A→B→C→D→冻结→E→F 推进。旧 contextual runtime 保持 reference，不将其 frontier、维护终结、来源或持久化策略移入 B0。

当前工作从干净的 `197b75c` 开始。唯一 Sol xhigh 负责人处理依赖组、公开 Agent／provider 接线及窄检查；root 处理身份、环境、冻结、真实模型并发 1、成本与报告。现有 LangMem checkout 固定 `9d033b47d9ce53e37e92c92241b0496c0278932e` 且干净，未重复下载。

环境初查确认 Python 3.11.13 可用；当前 vLLM Host 启动参数没有 enable-auto-tool-choice 或 tool-call-parser。native 的真实可用性尚待兼容性 spike，不将静态配置当成功。长期 Store 候选为上游 PostgresStore；正在核对已有隔离实验 pgvector 服务以建立独立 Lab 数据库／角色，不连接旧 Product 数据库或部署新的存储平台。

正式行为验证只使用原冻结的 12 例诊断和暴露 arc0，不消费 seeds 3/4，不开始 B1／M1／M2。所有 spike、失败及复核进入独立 v15 连续账本，累计限制为 null。v14 的 80 次生成／317098 generation tokens／1540 embedding tokens 及负面结论封存不变。

独立依赖组已安装：LangMem 使用固定 Git 提交，实际安装的三个关键源码文件与 checkout 一致；LangGraph 1.1.10、prebuilt 1.0.13、PostgresStore 2.0.25、SQLite checkpointer 2.0.11，详细分发 hash 见 upstream manifest。旧 reference 47 文件中仅依赖元数据 pyproject／uv.lock 因新增组发生授权变化，45 个旧运行文件保持原样。

已有隔离实验 pgvector 服务中建立独立 `milai_lab_langmem_v15` 数据库和非超级用户角色；上游 PostgresStore 的 1024 维 content 索引 setup 与独立 SQLite checkpointer 已完成零模型验证。凭据只放 ignored 私有配置，没有访问或修改已有 Product 数据。

native 真实预检返回 HTTP 400：现有服务未启用 auto tool choice/parser。此请求没有 usage，连续账本保留 4891 tokens 预留与 unknown=1，不能当零成本。随后曾创建带 parser 参数的临时容器；用户要求保留 vLLM 设置后立即撤回，临时容器未收到模型请求。原容器使用 AutoRemove，停止后自动删除，因此用保存的 inspect 和同一镜像重建：image、原始 command、entrypoint、environment、挂载、GPU、共享内存、网络、端口、restart 与 AutoRemove 均逐项相同。恢复容器为 `25f0a0dee927`，加载期间不发送生成请求。变更与恢复证据保存于 ignored 的 `artifacts/langmem-foundation/service/`。

固定适配身份改为 `langmem-hotpath-react-json-action-v1`／`json_action`。边界将结构化 JSON 的 final 或有序 calls 转成 LangChain 消息，调用实际 LangGraph ReAct 与上游 LangMem 工具；保持默认工具 schema、说明和返回内容。坏 JSON、截断与不合法参数不会被截取执行。零模型检查已验证两个记忆调用依次执行并正常最终回答，真实 S1–S6 尚待恢复服务就绪后进行；不将 mock 或 JSON-action 结果称为 native parser 通过。

初版 foundation lock 已生成，明确 `DEVELOPMENT_RESOLVED_NOT_FROZEN`；最终源码与诊断输入冻结后再刷新。复用 v14 权重清单，13 份模型清单／元数据／tokenizer 检查一致，没有重复散列全部大权重。恢复服务内的 xgrammar 对实际 spike JSON-action schema 解析通过，该 CPU 检查未产生模型调用。

同 thread 离线检查定位了 LangGraph 的保留键冲突：`configurable.run_id` 会影响第二条消息执行，已改成 `foundation_run_id` 并保留 run／arm／user namespace 的语义隔离。每条公开消息的请求次数另外持久记录，跨进程续接不重置 12 次容量；未知请求也保留计数。

真实接线又定位两处消息模板边界：重复起始 system 消息在本地容量检查失败，已合并为一个；历史 native tool_calls 的参数字符串不适合本地 Qwen 模板，JSON-action 历史改为对应 JSON calls 正文，ToolMessage 的实际内容与 call ID 保留。第二处失败发生在业务动作之后，随后从原 checkpoint 续接，业务仍只执行一次。两次本地错误都没有额外发送失败的 HTTP 请求。

r2 出现两条 `content=null` 记忆。核对实际 schema 后确认字段存在；服务内 xgrammar 0.2.3 的零模型匹配证明 `content→action→id` 可生成，`action→content→id` 被拒绝，`action→id` 却合法。修复仅放宽生成 schema 中参数对象的字段顺序，原始工具 catalog／参数／默认值保持不变，执行前仍用完整原始 schema 校验。上游允许空 content、未知 ID update 为 upsert 等真实行为不被本地改写。旧 null 记录保留为机械失败证据，不计入冻结 B0 的语义成绩。

新隔离 r3 完整通过 S1–S6：四条公开消息、六次生成、3595 generation tokens；两次 embedding、25 tokens。一次响应完整执行业务动作和有效 memory create，后续同 thread 恢复有两条用户消息；新 thread 首请求只有 system＋当前 user。`nutrition constraints` 查询通过 bge-m3 索引取得原记忆，score=0.5576698613861267。新进程读取的 ID／正文一致，run／arm／user 隔离成立，业务只执行一次。三份核心文件与 CLI 均在这组 spike 内保持同一 SHA。证据见[spike 清单](../data/manifests/langmem-foundation-v15-spike.json)。这证明接线与持久化，不证明自然首次保留率或语义质量。

截至 r3 结束，连续费用为 12 次生成、11600 charged tokens（6709 known＋4891 unknown 预留）、25 embedding tokens，Judge=0；此前失败未清零。原有 64 个 locked packages 的版本未改，新增 37 个可选依赖。正式 12 例诊断和 arc0 仍须等待 C／D 完成与冻结。

C／D 已完成，7 项窄测试、可选组 7 模块及默认无组 99 模块 mypy、Ruff、默认可选测试跳过、lock 与 prepare 校验通过。最终 active boundary 曾拒绝 `datasets/merit.py` 的 `sys.path.insert`，该候选未进行正式模型请求。修为固定目录 `importlib.util` 包加载后，原路径列表不变，active boundary 与原 arc0 的窄 mock 回放通过；工具依赖边界也通过。原失败候选及 prepare 收据保留，未放宽检查规则。

首次正式 R1 源码映射为 `a686aa61f637aefed857204bdfb69134a5ed126909d7b0eb17603d1bb565c8a2`（22 文件），foundation lock SHA 为 `19b327b616f6f4f22674ca55eb194436c3b594d16a3e0c3d46965263b37b84be`。必要重建后的 sdist 含同一 lock 与 22/22 相同源码，包内无凭据或实验制品。r3 之后仅增加费用上下文、冻结／运行／汇总边界及固定包加载，生成适配语义未变，没有重跑已通过的 spike。

R1 两组正式配置分别通过 prepare，初始记忆空间均为空；先运行原 12 例／20 会话诊断，再尝试完整原 arc0。该轮身份已保留为 [R1 冻结清单](../data/manifests/langmem-foundation-v15-r1-freeze.json)。完整使用相同原始输入，rubric 与 gold 不进入模型；不因语义失败改 prompt 或换题。

R1 诊断 12/12 终结，人工语义 7/12；MERIT 完成前两集后，第 3 集返回有效 JSON、但 `manage_memory(action="search")` 参数非法。初版 facade 抛异常使整轮中断，没有交付可供 ReAct 继续处理的普通错误回执。该轮 34＋7 次生成和全部结果保留，MERIT 不认领完整分数，源码快照和部分结果见 [R1 清单](../data/manifests/langmem-foundation-v15-r1-results.json)。

Sol 在唯一工具边界修复：按原 schema 验证各 call，非法参数生成相同 call ID 的 error ToolMessage，工具 body 与业务 journal 不执行；同批合法调用仍顺序执行。核对发现上游 Pydantic args_schema 与业务 JSON-dict args_schema 的实际执行验证行为不同，因此通用 wrapper 覆盖两者，避免业务参数未经检查就执行。坏 JSON、截断和坏 envelope 继续硬失败。真实 LangGraph 离线回放完成非法调用→错误回执→修正调用→final，8 项 foundation 窄测试、静态和相关边界检查通过。未增加 prompt 语义策略。

R2 最终冻结源码映射 `99fba610b55237aa31de8ad7f25312dc65e847d944b44b3bde1cde572b3e5ef9`，lock SHA `e3b98d9ff15030afeb34eb7548edae3571230f1c20db89766ec7b0c5b12c4090`。必要的 R2 重建确认 sdist 同一 lock 与 22/22 源码；检查和包 hash 已保留于[最终冻结清单](../data/manifests/langmem-foundation-v15-final-freeze.json)。从原世界和全新空 namespace 完整重跑原 12 例／20 会话与 arc0 的 5 集／7 消息，无中断。

R2 人工诊断 7/12，原生 MERIT 4/5、dependent 1/2。诊断 d02 漏存回执、d04 未完成指定结尾，d08/d09/d11 已有记忆却不搜索；MERIT 首次约定 0/2 保留，并将无依据 5000 分写成约定后实际退款，原应为 1774 分。另一次正确退款留下过时 pending 正文。原生工具成功不等于参数有依据，技术终结不等于语义通过；这些反例进入[最终结果](MILA_LANGMEM_FOUNDATION_V15_RESULTS_20260926.md)，没有再调提示追分。R2 未自然复现 R1 的非法 action，真实错误恢复收益不能由两轮差异推断。

连续账本最终为 108 次生成、76737 charged tokens＝71846 known＋4891 unknown 预留，embedding 33 次／836 tokens，Judge=0。离线汇总与 trace、账本逐项一致；最终源码／验证文件、45 个旧 runtime、v14 封存费用、路线图和运行中 vLLM 原设置再次只读核对一致。镜像标签引用与恢复时的不可变 image ID 不同，但实际镜像字节相同。A–F 完成，G0–G5 技术 GO，结项 COMPLETE_WITH_BASELINE_FAILURES；未扩题、未开 v16、未更改 Product。
