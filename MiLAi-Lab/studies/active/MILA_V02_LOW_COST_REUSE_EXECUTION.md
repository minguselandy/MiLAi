---
document_id: MILA-V02-03-EXECUTION
date: "2026-09-06"
status: COMPLETED_KEEP_BASELINE
---

# MILA-V02-03 执行记录

> 更正：下文保留首轮3次分配的过程。通用 payload 修复及原定续做已完成至累计预算出口，
> 最新为17次分配/16模型会话、12次后续、3条完整历史对照；N5另一条确认历史后续未分配。
> 见 [修复与续做报告](MILA_V02_PAYLOAD_FIDELITY_CORRECTION_20260906.md) 和
> [累计总账](MILA_V02_PAYLOAD_FIDELITY_RESULTS.json)。

最终结果见 [交付报告](MILA_V02_LOW_COST_REUSE.md) 和 [分配总账](MILA_V02_LOW_COST_REUSE_RESULTS.json)。
共 3 次分配、2 次实际 G、482794 token。两份正常笔记均因公开首尾空白归一化而不能原样复制，
N4 NOT_EVALUABLE，N5 未进入；F/S 实际分配 0。仅本轮服务已停止，数据和失败记录保留，认证副本 0。

本轮执行 [实验合同](MILA_V02_LOW_COST_REUSE_PLAN.md)。旧研究与公网保持原状。
审查的三个 P2 已补入合同：实际在线/观测/保存成本分账、受检 evidence_refs、完整 State 与 state_id CAS。

N1 锚点在新候选结果前固定：计数 0a995998、普通 8550ddae、更新/组合 852ce960。
N4 历史固定 27016adc 与 852ce960；两者有前轮曝光，不称盲样本。
若进入 N5 保存确认，历史固定 ba358f49 与 cf22b7bf；与 R 不重叠，尚未用于本轮候选设计。
未来任务及来源支持条款在对应 G 前另行封存。仅复用中性 data-20260905b，禁止重读 500 corpus。

运行根目录：`artifacts/v02-low-cost-reuse/n0n1-20260906a/`。
改动前 Product testkit 与 manifest 保存在同研究 `baseline-code-20260906a/`，附 hash。
当前第一增量仅增加受控字段差异，不改变响应语义比较或检索。

以下为模型分配前的工程进度记录：N0 READY；N1 NEUTRAL_TRACE_READY；N2 审计已封存；
N3 有条件路径通过。随后模型阶段与最终出口以上述交付报告为准。

N1 第一批 2 次：旧 D1 ON 拒绝，仅 context/root 两个局部 ID 不同；D1 OFF 通过。
第二批 4 次：新 v0.2 计数、普通、更新、空来源均通过。未移除 observer/repository 门。
24 个定向 unit 通过；7 个真实 PG continuation 测试通过，含新增来源确实进入 Context 后的
中性拒绝，以及错误 query/scope/未知 predecessor 拒绝。初次 predecessor fixture 错把 409
预期写成 200，已依实际公共拒绝合同修正；旧失败日志保留。

Runtime Ruff/mypy/build 通过；完整 pytest 起初未配置数据库而失败，随后在本轮 PG 内新建
独立 `milai_v0203_checks` 数据库运行：962 passed / 1 skipped（Runtime venv 未安装 SDK，
跳过一个 context-chat 客户端集成测试）。此前7项定向 PG 在运行实例中执行。
Lab 最新 159 tests、Ruff、mypy、boundary、build 通过。N0 实际无模型容器边界与13工具目录通过，
Codex CLI 0.153.0；原题及未来问题从 G 历史包排除。

N3 发现 Runtime 递归 strip payload 字符串首尾空白，首次真实保存末尾换行丢失，回读未通过
精确性确认。第二个隔离测试误复用 operation ID 被拒绝，第三次独立 ID 的完整请求/回读确认
了 strip 原因。三份失败记录/非 Canonical State 保留，不重写或清空。第四次测试在保留内部
换行且无首尾空白的明确非模型 fixture 上通过版本、旧字段/引用、no-op、stale、operation
conflict、无效/跨 scope 引用拒绝。23 项封装单测通过。封装器现对不兼容文件提交前拒绝；
G 不接收改变文件首尾格式来迎合实验的指令。该限制可能使 N4 无合格复制机会。

专用网络默认池耗尽的 setup 失败保留；改用经路由检查无重叠的本轮 10.243.3.0/24。
没有删除或重启旧网络/服务。本轮实例与检查数据库在收尾时一并停止其自有服务，保留卷。
