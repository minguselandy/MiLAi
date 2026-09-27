# MiLAi 总体实验总结与 v2 暂停交接

日期：2026-09-28（Asia/Shanghai）。范围：MiLAi-Lab / RESEARCH_PROTOTYPE。
**实际 Goal 已暂停，总研究目标未完成，Product 仍为 NO-GO。**

用户最新明确要求“暂停当前实验，总结提交到github上，生成实验总结文档”。实际 Goal 于
2026-09-27 18:46:35 UTC（北京时间 2026-09-28 02:46:35）设为 `paused`，覆盖此前执行 v2 的授权。
Root 中断 Sol 开发任务；停止交接确认没有遗留的本任务实验、测试、构建或下载进程。
本次只整理证据、暂停记录和 Git 发布；共享推理服务保持原样。
未来恢复开发或实验须有用户新的明确继续指令，旧计划或记录里的 ACTIVE 不能恢复授权。

本报告承接[上一轮总体报告](MILAI_NEXT_IMPROVEMENT_OVERALL_EXPERIMENT_REPORT_20260928.md)，
补充 v2 的 N0 工程交付、N1 既有轨迹核对和 N2 未完成现场。
[机器清单](../data/manifests/milai-overall-v2-pause-20260928.json)保存账本、证据哈希、检查归属及 WIP 身份。
不同源码、任务和分母分别报告，不把历史结果合成一个总体准确率。

## 目前能够支持的结论

公开 LangGraph/LangMem 基底上的版本记录、请求副本投影、State 维护、严格 CRUD、真实回执和恢复接口已建立。
多轮检查支持这些工程接线事实，但正确材料送达、合法写入和工具执行成功，仍不足以保证任务正确。
现有小规模诊断反复暴露形成遗漏、语义维护错误、错误业务参数、容量路径和助手无依据声称。

尚无充分证据证明稳定的 unseen 收益、独立 A/U 选择价值、完整生命周期成本优势或第二模型家族泛化。
v2 尚未新增任何真实模型样本，因此 N0 的工程等价和 N2 的局部测试不能改变上述研究判断。
现阶段应保留强简单基线及负结果，不预定 Host 双写、selector、patch 或版本反馈必然是胜出方案。

## 历史实验总览

| 阶段 | 已有结果 | 适用边界 |
| --- | --- | --- |
| SER 开发控制 | 最终同源 13/13 | 机制开发验证，不是未见收益 |
| v23 原始 MERIT 两个 arc | B1 6/10，A3/A4 各 7/10 | 没有自然 refresh/rebase，分数差不能归因为 SER |
| v24 formation / reconciliation | 三种形成提示各 0/2；修订 strict 2/3，必要维护 0/1 | 已停止这些提示家族；CRUD 可执行不等于正确维护 |
| v25 应用 | 8 次冻结运行，覆盖持久化、交错、双用户、部分副作用和重启 | 保留过期行动、容量循环、错误 key、虚构 ID；fresh-session 成本差不是压缩效果 |
| v26 原生 Mem0/B1 | strict 4/4 对 2/4；生成 tokens 53,852 对 5,324，约 10.1 倍 | 4 个已暴露样本、不同系统契约；ADD-only 不证明同 ID 修订 |
| 历史 LSA 16 轮 | G/L 匹配各 60/78，LRU 59/78；完整历史相近或更好 | 消息嵌套于情景，不是 78 个独立样本；结论限对应旧源码 |
| E2 固定前缀 | post-event 10/12，turn-start 11/12 | 首响应诊断，不是在线生命周期效果 |
| E2 在线比较 | 两组均 7/11，完整轨迹均 0/2；tokens 54,453 对 33,039 | 形成内容、普通 memory、时点和错误路径共同变化，不能作纯时点消融 |

各阶段原始证据入口：[SER](MILAI_SER_V21_FINAL_RESULTS_20260927.md)、
[MERIT](MILAI_SER_V23_RESULTS_20260927.md)、[v24](MILAI_LIFECYCLE_V24_RECONCILIATION_R2_RESULTS_20260927.md)、
[v25](MILAI_APPLICATION_V25_RESULTS_20260927.md)、[v26](MILAI_EXTERNAL_MEMORY_V26_RESULTS_20260927.md)
及其[复现说明](MILAI_EXTERNAL_MEMORY_V26_REPRODUCTION_20260927.md)、
[LSA 16 轮报告](MILAI_LOCAL_STATE_ATTENTION_OVERALL_EXPERIMENT_REPORT_20260927.md)、
[E2 复盘报告](MILAI_LSA_REVIEW_OVERALL_EXPERIMENT_REPORT_20260927.md)。
旧 M1、持久 Decision State、结构化 ODR 和 v27 模型候选草稿均未自动恢复。

## 最近完成的真实实验

| 切片 | 样本与结果 | 实际生成费用 | 决策 |
| --- | --- | --- | --- |
| WP6 表示与续接 | 两个已暴露 arc × 三种表示，共六条路径，strict 1/6；六次真实 SQLite 写入忠实执行五个错误提案 | 首响应 6 次 / 7,605 tokens；续接另 6 次 / 8,846 tokens；embedding 327 tokens | 标题变化未修复主要错误；停止措辞变体，保留真实行动失败 |
| C3b 写入职责 | 一个 arc 两前缀；Host 双写 2/2，边界双写 1/2，Host memory + turn_end State 2/2 | 分别 11,629 / 17,528 / 13,421 tokens；共 15 次生成，embedding 200 tokens | 保留简单职责候选，但不能宣布长期最优或生命周期节省 |
| C4 整体替换与普通 patch | 一个 arc 两个构造前缀；replace 2/2，patch_or_replace 1/2 | 各 2 次生成，3,467 对 3,675 tokens；embedding 0 | 无质量或成本优势信号，保留可选接口，停止本轮变体 |

WP6 的首断点是 Host 行动提案。竞争解释包括标题锚定，以及旧助手文本、普通 memory 或增量消费干扰。
来源精确标题未修复错误；raw_sources 同时改变 State 存在及材料角色，不是纯 State 消融。
真实 ID/数量/标签回报 6/6 和保守回答忠实性 5/6 都不能替代任务 strict 1/6。
详见[首响应](MILAI_NEXT_IMPROVEMENT_WP6_PRESENTATION_20260927.md)与[续接](MILAI_NEXT_IMPROVEMENT_WP6_CONTINUATION_20260928.md)。

C3b 失败的实际控制响应同时提出两个 UPDATE 却缺少 content。旧 ordinary memory 合同写入 null，
State 拒绝；后续模型只修好 State，Host 仍宣告完成，未满足两种记录和有用回答的冻结判据。
确定的接口损坏已由独立 strict 正文护栏修复并零模型验证，但原失败不重判，也没有重跑成为成功样本。
Host 双写这两个前缀总 tokens 比 overlap 少约 13.4%，增量单例却更贵，不是完整生命周期收益。
详见[写入职责结果](MILAI_NEXT_IMPROVEMENT_WP3_WRITER_POLICY_20260928.md)。

C4 的失败臂选择整体替换回退，要求移除一个目录可见、却未绑定当前 State 的证据链接。
合同拒绝后零写、pending 保留，必要维护未完成；这不是字面 patch 匹配失败。
竞争解释是模型混淆可见来源与已绑定链接，或严格拒绝规则增加接口摩擦。
没有事后放宽合同或只给失败臂增加修复机会。详见[局部更新结果](MILAI_NEXT_IMPROVEMENT_WP5_LOCAL_UPDATE_20260927.md)。

## v2 本次新增证据

v2 实际采用的原计划为 [NEXT_DEVELOPMENT v2.0](MILAI_NEXT_DEVELOPMENT_PLAN_20260928_v2.0.md)，
SHA256 `84d5ddd45224d83c4206c95d8b46ca41f2a5dabd9990266aadccae0df1c0df22`。
原 Goal 写的是同日期 `NEXT_IMPROVEMENT` 文件名，现场不存在；执行时已披露该差异，采用唯一同日期/版本文件。
原计划逐字保留，未伪造同名文件；最新停止指令现在优先于此前执行授权。

N0 已发布为 `ddd5ab71bcc213eb97c52b22698ff9ed4ac1f8ae`，见 [PR #61](https://github.com/minguselandy/MiLAi/pull/61)。
从原 C5 WIP 抽取共同 selector 提示/载荷函数，不混入 N2 行为改变。
旧 cf1588a 与新实现的 35 个 scripted 场景、45 个控制请求及 bank 调用顺序、回执、pending、容量记录完全相同；
完整有序 JSON SHA256 均为 `1b3069b6a44ef41de18a8ca999eb39dff2d52ac251bfe8dd2dd9a29b7e6edbfb`，未删字段或规范化。
这只证明所测 fake Bank/scripted model 合同等价，不是 raw HTTP 字节或真实 Store 的全面证明。
71 项协议检查、11 项相关 foundation 检查及目标 Ruff/Mypy 通过。
初次 Ruff import 分组失败及最小修复保留；没有重复整套本地测试或无关构建。

N1 只读核对既有 C3b 增量 boundary 失败的真实 trace：缺 content 已在原模型响应中；
null ordinary 记录与实际成功/error 回执确实进入后续 Host/修复控制请求，修复控制只调用 manage_state。
因此，对这条轨迹，“真实回执未送达”的解释已排除；材料被语义误用、修复只聚焦 State 的解释仍保留。
交付不等于采用，不能将单条轨迹外推所有失败，也不据此追加措辞试验。
源码、检查及原始 trace 身份见 [N0/N1 回执](../data/manifests/next-development-v2-n0-n1-checks-20260928.json)。
其中 `committed: false` / 尚未发布字段是原预发布时点记录；后续发布事实以上述 ddd5ab71 和 PR61 为准。

## N2 停止点与未运行部分

旧 C5 草案只得到首响应，没有 State READ 工具，无法验收完整读取与最终回答。
v2 已准备固定 bank、共同只读权限、all/query/query_enhanced/A/full_history 五条件的薄 runner。
输入来自一个已暴露 arc 的两个前缀，共计划 10 条读取路径，不是 10 个独立样本，亦不是仅 10 次调用。

输入核对还发现两个重要混杂：combined 旧历史缺少较早 session；两张“预约失败”卡由控制模型在业务执行前生成。
新输入准备补齐共同合法历史，保留全部原卡片并标明只是模型声称，未把 bank 修成理想答案。
background 5 条消息、combined 9 条消息；combined 当前问题明确替换为只读诊断，不称原生业务任务重放。
辅助 ordinary memory 统一为空，属于受控前态；full_history 仍有共同目录和 State READ 权限，不能当禁用 State 的消融。

**N2 输入/config/rubric 已登记固定字节，但源码、工具 schema、prepare、构建及执行身份未完成冻结；真实运行 NOT_RUN。**
停止时 Sol 交接：新与相邻 read_probe 窄测 12 passed，目标 Ruff 通过、Mypy 3 文件通过，
检查归属矩阵通过（active_sources 151、optional_tests_owned 13）。这些是停止前已完成的检查，Root 未为收尾重跑。
首次新测 1 failed/3 passed，因测试误认为 JSON-action 具有顶层 tools；修正断言后 4 passed，随后相关集合 12 passed。
首次 Ruff I001/F401 已修复。重复子集不叠加为独立测试数量。
零模型 prepare、必要包装 build/内容核验、最终检查回执、真实 Host/embedding/共享 Store 调用均未完成。
局部检查不能支持 freeze-ready、可复现运行完成或语义收益结论。

| 剩余要求 | 暂停状态 |
| --- | --- |
| N0/G1 整体准入 | N0 局部提取完成；N2/N3 新行为和执行冻结未完成，不能关闭整个 G1 |
| N1 消费诊断 | 单条既有失败的真实交付核对完成；无新增语义实验 |
| N2/X3 固定 bank 完整读取 | WIP；0/10 路径实际运行 |
| N3/X4 固定前态更新 | 仅 ignored 草案；0/8 诊断实际运行，无新 runner 实现 |
| N4 有限交付版本反馈 | 条件未触发；设计建议不是实现或采用证明 |
| N5/X5/G3 原生连续任务与构造补充 | NOT_RUN；旧 11 消息构造草案未冻结，不替代原生完整单元 |
| WP7 生命周期费用及复用摊销 | NOT_DONE |
| N6/G4 新任务族、强对照及第二模型 | NOT_TRIGGERED；第二独立模型族仍 NOT_RUN |
| 稳定 unseen 收益及 Product 迁移 | 未证明 / NO-GO |

## 连续费用与测量边界

| 范围 | generation calls | generation tokens | embedding tokens |
| --- | ---: | ---: | ---: |
| v1 后续改进起点 | 2,768 | 3,420,333 | 18,746 |
| v1 WP6、C3b、C4 合计新增 | 31 | 66,171 | 527 |
| v2 N0/N1、N2 准备及本次收尾新增 | 0 | 0 | 0 |
| **本次暂停时累计** | **2,799** | **3,486,504** | **19,273** |

权威账本是原 checkout 的 `MiLAi-Lab/artifacts/ser-v20/budget.json`，
SHA256 `bfc2768c4cd6d92ce650bc65e2018b8d23a404de0c9a61e07e88ccbd1c43d0c6`，与 v2 起点相同。
当前层 generation/embedding unknown usage 均 0；更早 sealed 历史按原记录保留，不抹去其中曾有的未知预留。
账本未清零，历史、失败、修复、空维护和初始化成本不重复累计或删除。
开发代理、CI 和文档工具费用不属于实验 Host/embedding tokens；未测量的货币、CPU、物理 I/O 不填 0。
现有网络时间与逻辑字节不是完整生命周期延迟或物理压缩率。

既有 Host Qwen3.6-35B-A3B-FP8，temperature=0、max_tokens=4096、thinking=false、容量 65536；
每公开消息 Host 上限 12，真实 HTTP 并发 1。Embedding bge-m3、1024 维。
控制调用沿既有单独上限，未借机调整共享 vLLM/parser/服务配置、部署新模型或下载权重。

## 检查、保存与发布

只读核实 [PR61 Fast 36341193969](https://github.com/minguselandy/MiLAi/actions/runs/36341193969) 已 completed/success，
最终 gate 为 108683211915。Lab/core、foundation、external、边界和 conformance 成功；
Product Runtime/integration、Archive 和 tested-tree-identity 的 skipped 不计通过。
此 CI 属于 N0 发布组合，不覆盖未提交 N2 WIP；本次没有重跑它。
本报告只做链接、JSON、哈希与差异检查，不启动 pytest、build 或模型实验。

原 C5 开发树 `MiLAi-worktrees/next-improvement` 保留原 2 个源码修改和 6 个 JSON，8/8 哈希未变。
v2 开发树 `MiLAi-worktrees/next-development-v2` 停在 `feat/lab-fixed-state-read-v2-20260928` / ddd5ab71，
保留停止时 11 个 N2 WIP 文件：4 个已跟踪源码/配置/CI 修改，7 个未跟踪 runner/入口/测试/协议/输入文件。
上述 11 文件原字节保留，不作为已验收实现发布；AGENTS 与执行记录另同步为暂停状态。
N3 ignored 草案、旧 v27 草稿、原始日志、模型元数据和本地资产全部保留。
精确路径、哈希及检查未完成项均在机器清单，不将本地文件存在误称 GitHub 已保存其全部内容。

报告使用从 ddd5ab71 建立的独立 `MiLAi-worktrees/next-development-v2-closeout`，
分支 `docs/lab-next-development-v2-pause-20260928`。Root 写文档/清单，Luna high 负责提交、推送和远端核对。
main 核实仍为 `9515017a5dfaba6b6e306fa778fd20f4383b6e35`；旧 PR 保留 open/draft，不自动合并或关闭。
本次不改变运行源码、Schema/API/权限或 Canonical 行为，回退基点为 ddd5ab71。
报告自身提交与 PR 身份由 Git 发布记录提供，避免自引用哈希。

历史结果须按各自方法提交、输入锁与 scorer 复现；旧真实续接依赖本地 ignored 首响应制品，
公共合成输入和精简结果并不意味着外部读者已获得全部原始轨迹。
秘密、DSN、原始私密轨迹、数据库、环境、权重、缓存和构建产物继续排除 Git。
若未来明确恢复，先核对实际 Goal、两处 WIP、服务和连续账本，再决定最小下一步；本报告不是恢复授权。
