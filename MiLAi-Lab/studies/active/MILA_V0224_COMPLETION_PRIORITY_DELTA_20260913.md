---
goal_id: MILA-V02-24
status: USER_DIRECTED_ACTIVE_EXECUTION_DELTA
supersedes: CPU_EFFICIENCY_BLOCKING_CRITERIA
model_http_allocation: SEPARATE_CONCRETE_STAGE_CONTRACTS
---

# 完成任务优先：停止 CPU 效率优化

用户最新明确指令：“优先完成任务，不要卡这么严格的计算效率，这样优化是无意义的”。
本指令优先于此前 v0.3 和技术子合同中的 CPU 效率验收要求。

停止压缩、R05 静态缓存、新性能候选及重复余量校准。R05 仅完成开发与准备合同冻结，
实际准备未启动，当前冻结不再执行。所有历史源码、失败和诊断证据保留。

18 秒 runtime 余量、90 秒链余量及 CPU 阶段效率预算只作为历史或描述性测量，
不再阻断后续执行或科学结论。不为达到这些数值修改保证、再造 profiler 或反复校准。
实际耗时和所有成本仍如实记录；必要的挂死保护不被解释成科学结果。

原 R04 A1 的四轮/两动作、24 rows、120 层校验、六组独立效果与 SQL、完整退出已经有效。
旧报告中的效率失败不改写；按此新指令，其正确性证据可支持直接进入完整 K3，
无需新 R05 或再跑一次 A1。运行时继续使用原 R03+R04 静态/动态验证方式。

仍完成完整 16+80 reference、24 效果链、40 个冷进程、父 finish/gate 和当前工程检查。
不跳过完整意图、目标/值/顺序、权限、隔离、CAS、幂等、回执、World readback、
历史账务及未知用量停发。后续 B–E 的科学矩阵、普通 Note/同调用 review、
完整分母及公开 Product 边界保持；每批实际模型/HTTP范围分别明确。

完成 K3 正确性与工程验收后，使用 `GATE_A_FUNCTIONAL_PASS_UNDER_R03_R04_USER_PRIORITY`，
注明 CPU 效率已按用户要求退出阻断条件。不能追认旧效率门已通过，也不能冒称 R05 已执行。
此修订直接来自用户，不需要再进行一轮空白效率许可审查。
