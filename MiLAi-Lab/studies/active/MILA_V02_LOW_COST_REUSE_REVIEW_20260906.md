---
document_id: MILA-V02-03-REVIEW
date: "2026-09-06"
status: REVIEW_COMPLETE_WITH_CONTRACT_GAPS
scope: DOCUMENT_AND_CURRENT_IMPLEMENTATION_REVIEW
experimental_model_allocations: 0
---

# MILA-V02-03 开发实验 Goal 审查

审查对象：[Product Goal](../../../MiLAi-Product/docs/goals/MILA_V02_03_可信诊断与低成本记忆续做_开发实验_GOAL_20260906.md)
及其规范性依赖[Lab 实验合同](MILA_V02_LOW_COST_REUSE_PLAN.md)。
结论：目标、阶段安排和边际成本估计成立，未发现需要推翻方案的方向性问题；建议在进入
N3/N4 实现与效果分配前补齐以下三处中等风险合同缺口。它们是计划与待复用实现的衔接问题，
不表示尚未编写的新候选已经发生错误，也不把“未创建执行清单”当作文档缺陷。

本次仅审查；原 Goal/计划保持 PLANNED_NOT_STARTED，未修改其正文、源码或旧实验结论，
未启动实验模型、数据库或服务。以下纯函数检查不是 N1/N3 的真实 PG 验收。

## 发现 1：在线墙钟还需明确剔除现有 runner 的观测成本（P2）

位置：Goal §7、§8；Lab §7.1、§7.3。
计划正确地把独立观察 GET 等列为研究开销，但没有明确旧 runner 中另外一次
`debug prompt-input` 的归属，容易把旧 `elapsed_seconds` 或 `phase_seconds.host_online`
直接当成新实验的用户路径墙钟。

证据：

- [v02_codex_container.py](../../tools/v02_codex_container.py) 第43–75行：真实 exec 之前另开
  一个容器运行 `debug prompt-input`，其目的为导出初始输入。
- [v02_lme_host.py](../../tools/v02_lme_host.py) 第70–102行：计时先于 launcher，
  `host_online` 包含该额外诊断；总 `elapsed_seconds` 还包含会后 observer GET 和日志处理。
- 前轮10次 L4 的 `host-phase-times.json` 显示，单次诊断导出为4.296–12.521秒。
  这是历史测量事实，不是对新候选的性能预测。

影响：N4/N5 的墙钟门槛是净节省严格大于0，秒级非用户路径开销足以影响临界取舍；
F/S State 不同也不能保证额外观测成本精确抵消。

最小修订：分开固定 `operational_online_seconds`、`instrumentation_seconds` 和
`delta_save_seconds`。前者保留真实 launcher/prefetch、正常 bootstrap、模型和工具成本；
独立 prompt-input 导出、observer GET 和观测处理单列。checkpoint 所必需的确认计入
Delta_save，不能因同样使用 GET 就全部划为研究开销。优先在计时段外进行独立诊断；
如按可测时段扣除，说明边界与残余影响。原始总墙钟和watchdog预算仍照计，旧结果不重算。

## 发现 2：笔记封装应明确使用 Runtime 实际校验的引用字段（P2）

位置：Goal §6“来源/保存”；Lab §5输入、规则2–3及资源/来源测试。
文档要求真实引用映射和 Runtime 资格校验，但待固定的封装结构尚未明确引用必须进入哪些
受检字段。把带 UUID 的 Markdown 原样放入 `text` 并不能自动验证这些引用。

证据：[host_cognitive_state.py](../../../MiLAi-Product/runtime/src/milai/domain/host_cognitive_state.py)
第65–85行的 `extract_evidence_refs` 只递归识别 `evidence_id` 和 `evidence_refs`；
不扫描普通字符串，也不识别 `evidence_ids` 这个近似字段名。
本次纯函数复核：同一个构造 UUID 放在笔记正文、`evidence_ids`、`evidence_refs` 时，
提取数分别为0、0、1，没有数据库写入。

影响：若新 wrapper 只保存笔记正文或使用未识别的元数据键，公开写入可能成功，却不足以
支持“笔记引用通过 Runtime 资格校验”的实验声明。引用存在和自然语言事实受支持仍是两层。

最小修订：在 N3 编写前冻结 managed 字段结构；笔记原始字节不改，实际 Evidence 引用另存
为保留字段 `evidence_refs`。核对待校验的引用集合与实际来源映射，不以空提取集合追认校验
通过。若允许纯文件来源，另标文件身份/资格审阅，不声称 Runtime 已验证文件正文里的引用。
补“正文含无效/跨项目 UUID，但未置于受检字段”的反例，验证封装器能发现遗漏；保留已有
跨项目引用的真实 PG 拒绝测试，不修改 Runtime 引用语义。

## 发现 3：已有 State 的完整读取与更新前置条件需写全（P2）

位置：Goal §6“原状态/保存”；Lab §5输入、正常与写入失败测试。
输入列出了完整旧 payload、expected version 和 operation ID，但应明确同时携带实际
`state_id`，并限定什么 GET 响应可用于完整替换式合并。

证据：

- Runtime [输入模型](../../../MiLAi-Product/runtime/src/milai/domain/host_cognitive_state.py)
  第34–48行：更新是完整替换；`expected_version>0` 必须同时有 `state_id`。
  本次纯校验中，version1不带state_id被拒绝，带合法state_id才通过输入校验。
- [公开状态封装](../../../MiLAi-Product/runtime/src/milai/application/host_cognitive_state.py)
  第105–118行：EXPIRED 返回非零version及state_id，但 payload 为 `{}`，不代表旧内容为空。
- MCP [有界输出](../../../MiLAi-Product/integrations/mcp/src/milai_mcp/server.py)
  第456–467行：超限可以返回仅含 `TRUNCATED/MCP_OUTPUT_LIMIT` 的结果，而非完整 State。
  Runtime 允许的payload大小与MCP整个响应的大小上限也不是同一量。

影响：直接照列出的输入调用会让已有H更新失败；把非完整响应当空 State 合并则违反
“保留旧字段/引用”的承诺。现有 Runtime 的校验/CAS 会拒绝部分错误操作；这里并未证明
其会接受越权或静默覆盖，也不需要更改其语义。

最小修订：创建仅接受 ABSENT/version0/state_id空；已有状态仅接受完整 ACTIVE 响应，
提交其真实state_id/version及合并后的完整payload。EXPIRED、TRUNCATED、缺字段、错误
schema/scope/authority不得降级为空对象；有公开完整读取路径时核验后使用，否则拒绝该次
checkpoint。补状态矩阵测试；不得用私有表读取恢复不可见payload或重置共享head。

## 已成立的设计与逐阶段审查

| 范围 | 审查结论 |
|---|---|
| 起点与旧结论 | 前轮14分配/13真实模型、两条负净收益与当前总账吻合；新实验没有倒算旧结果 |
| N0 | 新pin、安装核验、中性ID、未来问题隔离及预算检查齐备；执行清单按计划稍后固定合理 |
| N1 | continuation含局部ID与当前源码吻合，原始差异尚未证实；文档正确保留为假设。负控、PG、版本化及不删除中立性检查合理 |
| N2 | 保留原参考、AMBIGUOUS不计二值胜负、澄清题另立身份，能避免由A0答案反推gold |
| N3 | 原样复制、4096 UTF-8字节、no-op、旧字段保留及无模型边界合理；补发现2/3即可明确公开接口落点 |
| N4 | G只运行一次，F保留实际自然State和所有文件，S使用真实增量保存，两个未来独立分叉；因果对照成立，墙钟细分需补发现1 |
| N5 | 两条互斥路线及复核门槛明确；应按文中要求在首次分配前封存案例和顺序，不能事后挑胜例 |
| 成本与预算 | 4+12+12=28；240万token是启动软停线而非硬上限；未知用量不补零，阶段额度不自动转移，口径自洽 |
| 退出 | 不足两条、N1未解决或预算不足不冒充通过；N1未完成时可以继续公开F/S研究，但完整终态仍须遵守必要工程未完成→PARTIAL的规则 |
| 不变量 | A0、D2 SHADOW、Formal不正式评分、公网不变、无自动维护及Schema NO-GO保持一致 |

另两项执行提醒，不列为阻断发现：

1. T6新增来源必须确实改变所比较的 snapshot/READY 身份或有效候选；先验证干预命中范围。
   三次读取同一固定历史边界时，不能仅凭发生了新写入就推定返回语义必然变化。
2. N3 no-op应冻结“字节及必要元数据等价”的具体判定；自然State只有语义近似摘要时，不能
   悄悄引入模型等价判断。记录已有覆盖/重复程度，仍保留自然H。

## 审查证据与范围

审查版本：Goal sha256 `7f157901512d323e60ead8a62aca3a099741e3597abb34abba6187dba46d7adc`；
Lab计划 sha256 `37f947e365e19197234f507704e4d85212f50240cd6b4669f7c5a4f5e15e6aa0`。
已通读两份文档，核对前轮总账、第二次testkit错误、当前比较函数/续取assertion、State
公开合同和Host计时实现。两份文档本地链接目标全部存在；新增审查记录另做链接/格式检查。

纯函数复核使用Product runtime已安装Python，只验证输入模型和引用提取，无网络、模型、PG
或运行状态写入。没有执行N0–N5、重跑前轮实验或宣称本轮测试验收通过；未运行包级
pytest/build，因为本次只增加审查文档，无可执行源码变更。原计划及历史数据保留原样。
