---
status: ACTIVE
scope: MiLAi-Lab / RESEARCH_PROTOTYPE
reference_commit: 4aea99de0b7e058e2d254bf8860d0aba6d6b48db
plan_sha256: 079f8bfb6cdefbe4da11696d29b6f6cc74755f81337bdbfe3996add000cf18dd
---

# Local State–Attention 执行 Goal

用户已明确要求详细阅读并完整执行
[736 行原规划](MILAI_LOCAL_STATE_ATTENTION_DEVELOPMENT_EXPERIMENT_PLAN_20260927.md)。
本 Goal 保留 P0–P7、WP1–WP5 全部范围，不把完成定义收缩为 P1 原型或局部测试。
原规划字节不变；其中“拟议、尚未执行”是授权前状态，后续进展记录在此。
旧 `MILAI_MODEL_SENSITIVITY_V27_GOAL.md` 是独立过时草稿，不恢复其下载/部署。

## 当前事实与责任

授权开始时 main 与远端均为 reference_commit；v26 85 个 source 和 8 个 validation
文件哈希匹配。只有两份用户提供的未跟踪规划，没有预存 LSA 实现。当前实际 thread Goal
为 active；新会话没有可复用的旧代理，已启用一名 gpt-6-sol/xhigh 源码负责人。

Root 独占 docs、AGENTS、合成输入/rubric、阶段选择与冻结、所有真实模型/embedding 调用、
评分、成本及报告；Sol 独占 LSA 源码、必要共享接线、config、根 CI 和相邻窄检查。
Luna high 按需下载和已授权 commit/push；Astra xhigh 仅处理具体困难问题。
真实 HTTP 并发 1，开发代理不能替代实验 Host 或 Judge。

既有 Host 为 Qwen3.6-35B-A3B-FP8/7860，temperature=0、max_tokens=4096、
thinking=false、context=65536、每公开消息 Host 最多 12 次；embedding 为 bge-m3/7861、
1024 维。不改变既有 vLLM 服务；控制器预算单独声明且计入总计算。
连续账本 `artifacts/ser-v20/budget.json` 从 863 生成 / 1042729 generation tokens /
9617 embedding tokens 继续，历史成本链不清零；既有 exact-version reads 为 107。

## 完整执行与证据清单

| 阶段/工作包 | 必须交付的证据 | 当前状态 |
| --- | --- | --- |
| P0 / WP1 | 方法关闭 B1 请求/工具/持久状态对照；锁定公共 hook；实际 run_manifest；来源权限及计费角色 | R2 实际 decoder/manifest/独立计费正常；仍需补实际删除血缘与内部Store读计量 |
| P1 / WP1 | bank、独立共享维护器、U/A、实际视图；两条完整交错轨迹，含跨进程、新 session、真实部分失败与恢复 | R2 完成12消息，任务9/12、完整业务1/2；存在状态污染/焦点/Host参数错误，方法未通过 |
| P2 | 同 bank 的扁平/普通检索/State-conditioned 读取；组合与交换/缺项/错误状态诊断 | 四个实际R2断点已固定12个读取job及3个单列诊断；runner检查/构建完成，待发布后实际冻结调用 |
| P3 / WP2 | G/L/LRU 同维护机会、来源权限、预算、降级策略的小样本重复比较 | 未运行；初始建议 6 情景×3 臂×2 重复，调用前固定 |
| P4 / WP3 | 信号出现后 LR、U=A、R；六项关键消融及跨模板验证；共享约束、高耦合与错误状态反例 | 未运行，遵循进入条件 |
| P5 / WP5 | 新 frozen 原生 selection、第二任务族、交错顺序及完整重复；原 scorer 和失败分母 | 未运行；不消费旧暴露任务作 unseen |
| P6 / WP4–5 | N/d/a/r/H 代表点、质量—成本边界、第二模型族；有瓶颈证据才训练 selector | 未运行；第二模型仍缺独立端点 |
| P7 / WP5 | 无模板提示的模拟协作应用、复现命令、失败分类、强对照与论文证据包、发布及远端核对 | 未完成；Product 仍 NO-GO |

P3 的建议规模与后期 3–5 次重复在各阶段冻结前按方差/资源确定，不能结果后删失败或改分母。
只换名称/数值不算跨模板泛化；§15.2 十二种组合须在输入覆盖表中逐项映射。
完整历史、滑动窗口+摘要、强工作笔记/统一短维护器必须进入相关强基线判定；
B1/Mem0 系统对照与表示/注意力消融分开，不用被动 B1 代表全部 LangMem 能力。

## 实现与验证不变量

- 复用 BaseStore 独立 owner namespace；程序拥有 ID/revision，模型不生成 UUID/hash。
- 一个真实事件有稳定来源 ID；同文本不同事件不能去重；原消息、工具 JSON、checkpoint 保留。
- 独立控制入口不递归调用 Host；Host schema 保持 answer/calls，控制与 Host request 绑定分开。
- 当前用户纠正、所有真实工具结果（含 ok=false）均可见；部分副作用不回滚、不因维护重放。
- 单条坏编辑独立跳过，相关 pending 保留；无变化无新版本；共享原子组不能半组声称完成。
- 可选控制错误退化并计入主分母；真实数据库/权限错误显式隔离，不冒充模型语义失败。
- State 是可错的估计，引用合法不等于支持；pending 状态不静默宣称为已核对当前事实。
- 原始来源、索引、State、队列均计存储/访问成本；匹配臂权限相同，不读取 gold/未来事件。
- 删除覆盖 State 与缓存引用；撤回潜在影响和历史查询用途分开，scope 不可软回退。
- 根 `.github/workflows/fast.yml` 执行新窄测；完成切片运行实际受影响 foundation/journal/
  集成/包装检查；不跑全套 benchmark，不为发布重复成功检查。

每次运行由真实入口生成一个 manifest，自动绑定 Git/实际源码、config、依赖、模型参数、
输入 hash/split、arm/repeat、阶段计费/异常和输出。Root 在调用前冻结 source、输入、rubric、
顺序与隔离方式，并独立核对实际 HTTP→持久化→后续上下文→回答/动作。
不新建一套与运行入口重复手抄的参数/方法/输入清单；旧 source locks 原字节保留。

## P0/P1 的首个断点与竞争解释

当前源码没有 LSA bank、控制调用和前置视图接线。既有 B1 在 formation 上的失败不证明
新方法必然有效；先实现新机制，再以真实链路检验。

H1：普通 Host 自选 CRUD 的维护机会不足导致未来信息未保存。
H2：观察已到达，但缺少可持续状态视图/恢复路径使后续任务无法使用。
部分失败另比较 H3：模型将 ok=false 当成全失败，与 H4：跨进程事件/pending/状态接线丢失。
最小区分证据是公开输入→事件→控制 HTTP→真实 Store 写入→新 session 视图→业务回执，
不能靠 schema、进程 exit code 或测试通过替代语义判断。

P1 输入使用新合成事项；所有 State 与 U/A 由方法自行产生。轨迹 A 覆盖三事项、后台局部
修订、前台保持、新会话恢复及组合行动；轨迹 B 覆盖部分提交、跨进程读取实际对象并继续，
并检查第二用户隔离。复用既有 ApplicationWorld，不把正确分组或参数注入运行器。
rubric 与脚本分离，runtime 不读取 rubric；这些实例从首次执行起记 development。

[P1 输入协议](../data/manifests/local-state-attention-p1-protocol.json)已固定两轨迹、12 消息、
各两阶段的独立进程顺序与 rubric。源码完成并已交接冻结，协议当前为 PRE_REGISTERED_READY_FOR_SOURCE_PUBLICATION；
这不是已执行记录。Host 12 次及 controller 13 次为每公开消息容量上限，控制输出 2048 tokens、
Host 输出 4096 tokens，真实 HTTP 仍串行。服务 `/v1/models` 只读核对为原 Qwen/bge-m3，
生成窗口 65536；此次核对没有生成或 embedding 调用。

Sol 已完成 23 项相关测试：`tests/unit/test_local_state_attention.py`、
`test_langmem_application.py`、`test_langmem_foundation.py`；目标 ruff、7 文件 mypy、
core 110 文件 mypy、package/tools boundary 与 diff 检查通过。两条新脚本的 CLI prepare
均零模型通过。最终 build 已通过，sdist `4363d01093d0411d94e5b34299aa5ad344fb4fcc67b713e324d717d4d0ed75a7`、wheel `22855bf1325d25ddbd51fed1993b82fbb836c831f51eca6f399c3b4fc310cce9`。最后一次重建对应删除视图源码变更；没有为了发布重跑已通过组。以上证明工程接线，
不代替 P1 真实内容/副作用验收，也不证明后期消融、规模与泛化。

P1 实现是小 bank 全目录和原始事件逐项读取，尚未交付规模检索、原子共享更新组、归档/
重新激活和完整 G/L/LR/LRU/R 对照。源码相关问题已修正：到达序号替代 hash 排序；新建
引用绑定原编辑索引；LSA 显式关闭 SER；删除身份阻止旧 checkpoint 内容重新进入 State，
发送副本在删除来源后的下一条真实用户消息处重新开始，避免旧助手复述泄漏；原 checkpoint 保留。原始 DB 写入故障显式失败并保留 pending；
可选控制超时/截断允许 Host 继续。真实 Postgres 只读连接和现有依赖已核实可用。

## P1 实际进展

原型提交 `031acc7ae63353ac00ef237755b7b028ef8ae989` 已与远端 main 核对。
[R1 失败记录](MILAI_LOCAL_STATE_ATTENTION_P1_R1_RESULTS_20260927.md)确认新建 title
在 schema 可选、bank 必需，导致三次合法 HTTP 输出均未形成 State，pending 被保留。
实际运行 3/12 消息，Host 当轮 3/3 完成不能替代 State 验收；后九条未运行，不替换。
同一 Sol 仅修复通用字段契约，Root 将冻结新版本并重跑两条完整原 development 轨迹。
累计成本为 869 generation / 1048218 generation tokens / 9617 embedding tokens。
P2–P7 和完整 Goal 保持 ACTIVE。

R2 通用契约修复已冻结：创建必须有标题，更新可保持省略字段，focus 限于当前真实 ID
或本批新建短引用；10 项 LSA 窄测、相关 ruff/mypy/diff 通过，没有重新 build 或模型探针。
[R2 协议](../data/manifests/local-state-attention-p1-r2-protocol.json)继承原输入及 rubric
字节和顺序，新的源码发布后由实际 prepare 生成运行身份。R2 首请求检验新 schema 的
真实 decoder 兼容性，P1 语义验收仍待完成。

[R2 实际结果](MILAI_LOCAL_STATE_ATTENTION_P1_R2_RESULTS_20260927.md)及
[精简数据](../data/manifests/local-state-attention-p1-r2-results.json)保留全部两条轨迹。
跨进程持久恢复与部分失败 ID 保持可用，但控制器在业务调用前虚构了行动结果，且存在
读取遗漏和独立 Host 参数错误。真实用户/工具历史保留，0 degraded/0 pending 不等同
语义通过。全部9张State无evidence_refs，当前删除关联和Store操作计量也需补。
累计903 generation /1082606 generation tokens /9626 embedding tokens。
先进行冻结同bank的P2条件使用诊断（不声称P1已完成），再由Sol实现单一通用修复候选；
P3仍未触发。临时Astra只处理这一个具体跨层问题，不是常驻审计或效果裁判。

[P2 读取诊断协议](../data/manifests/local-state-attention-p2-r1-protocol.json)固定
四个真实断点的同bank all/query/focus。bank由真实请求与已接受写入重建，并逐项核对
实际view；普通query用bge-m3相似度top2，只读focus额外调用单列计费。
所有原始Host历史、工具合同和模型参数保留；仅改变临时工作视图，停在第一answer/calls，
不执行业务动作。12个方法job按固定轮转顺序，另3个diagnostic覆盖人工选择的真实旧计划、
反事实值及完整真实部分失败回执。raw输入留ignored，协议绑定输入字节hash；rubric分离。
独立薄入口已通过4项窄测及ruff/mypy，实际冻结输入的临时prepare为15 jobs/0 attempts。
一次必要build确认新CLI在sdist、新模块在wheel；哈希见协议，正式manifest在发布后生成。

Astra建议的后续单一语义候选是来源身份保持的状态迁移：维护输入保留actor/call身份，
区分请求、用户陈述与真实工具观察，不把读取任务写成已发生结果；不同时改Host。
删除另外使用程序机械dependency_source_ids，累积旧值、当前来源及所有可见State依赖，
与模型evidence_refs分开；全bank可见时可能保守多删，必须报告。缺失旧依赖不能视为无依赖。
这些是待P2证据决定的开发项，未实施/未验收，不能据建议声称问题已经解决。

## 后期资源准备记录

已核对 [LangMem 官方 API](https://langchain-ai.github.io/langmem/reference/) 确实区分
memory manager、store manager 与普通 tools；强基线不能只代表后者。
LangGraph 官方 reference 页面本次抓取返回 unsupported content-type，实际本地锁定源码
`chat_agent_executor.py` 提供 v1 pre_model_hook/llm_input_messages，以本地 mock 接线为准。

[MemoryArena 官方站](https://memoryarena.github.io/)链接公开源码与数据，数据卡声明 CC-BY-4.0；
[源码 README](https://github.com/ZexueHe/MemoryArena)说明当前为 preview、各环境需独立准备。
已按需委派 Luna high 仅固定官方源码与数据元数据，不安装环境、不读取/下载题目正文。
Root 浏览 Hugging Face 数据卡时，网页自动呈现了 bundled_shopping ids 0–17 的问题/答案
片段；这些不得在后期无披露地声称未见。当前未选择样本，未接入 runner 或宣布该任务族可用。

[资源回执摘要](../data/manifests/local-state-attention-resources.json)确认复用既有
`reference-sources/contextual-v7/MemoryArena`，源码 SHA
`6cd9de14b71915e39ac742a20dc33785e14b6aab`；数据 revision
`da1a37c8b19280e18627ca01cf368195a5e1d92e`。只新增 4762 字节数据卡，JSONL 下载为 0。
源码未发现根级 LICENSE，子目录 MemoRAG 许可不能代表整个仓库；不复制其实现进入公开交付。

[RIMs](https://arxiv.org/abs/1909.10893)和
[HiAgent](https://aclanthology.org/2025.acl-long.1575/)分别已有稀疏模块更新、子目标工作记忆
研究；本方法不以“多个 State”主张首次性，后期仍需操作级比较与独立收益证据。

## 失败、决策与完成审核

每个失败阶段记录 Observed、Expected、实际链、首断点、至少两种解释、最小区分实验、
通用修复与反例、混杂、完整成本和 Continue/Simplify/Redesign/Stop 理由。
保留全部失败、重试、退化、空维护和观察开销；不拼接最好轨迹。

结束前逐项审核原规划 §4–11、§12 阶段、§13 强对照、§14 六消融、§15 泛化、§16 指标/
重复、§17 预算曲线、§19 六组测试、§21 证据链、§22 五工作包。条件项须有证据决定，
未运行的必要项不能称完成。第二模型/公开独立任务族尚缺资源时如实 NOT_RUN，
继续可独立推进工作，不拿资源缺口关闭整个 Goal。
源码/config/合成输入/rubric/精简结果/文档由 Luna 发布；私密 DSN、raw 轨迹、DB、venv、
weights/cache/build 留在 ignored 目录。每次发布核对远端 SHA 和预期工作树。
