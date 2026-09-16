# V0224：按完成优先补齐 CPU 验收

用户再次明确“优先完成任务，不要卡这么严格的计算效率”。本修订落实该指令，
不恢复 R05、压缩、缓存或计时优化。旧实例、判据、失败和已经产生的成本保持原样。

原 K3 P3 已实际完成 16/16；P4 前 8 条已实际通过。第 9 条完成四轮 Session、
World 与 worker-result 后，在退出前校验期间被旧外层 300 秒限制终止：
子进程实际 -9、303.081 秒，父工具 24316 / 2dd7d7 实际退出 1。
该条不能因为业务结果已写出而追认为干净退出。
失败终态绑定在 raw `20260913-a-completion-priority-v1/P4-failure-external-terminal.json`，
SHA256 `10838aed8f4c21a73d10e35ece7ca75f8da5ea48e901d0b238f6ae7d359363a0`。

新实例只补原 P4 第 9–24 条，共 16 个新冷 worker；原 217 个冻结源码不改，
旧 coordinator 的 FAIL、stop、PASS 行都不改。新的 coordinator 只含这 16 个待执行位置，
不复制旧 PASS 行。旧完整 16+80 reference 与已通过位置只读复用，不重复生成或执行。
逻辑位置 id、scope、动作与输入保持不变；实际尝试由 batch root、binding 和 PID 区分，
新的业务 SQLite、operation journal 与进程均独立。

新单 worker 的 3600 秒与阶段 36 小时只作为有限生命周期保护，不构成效率成绩。
声明期限必须同时用于启动、claim、当前检查、父收口和事后 terminal 派生，
不能只改变外层 timeout，也不能通过修改原模块全局变量放宽旧合同。
R03/R04 的 fresh scope、原 Session、完整 B1/D11 接受、CAS、幂等、回执、
World 独立回读、计量和原始轨迹校验继续保留。CPU guard、MockTransport 与零真实模型/HTTP不变。

最终功能证据是一个明确的组合：旧 P3 16 + 旧 P4 8 + 新 P4 16。
这与“同一个新实例内一次完成 40 条”的保证不同，报告必须写明跨两个隔离实例完成。
若补全部分成功，则有 40 个成功冷 worker、41 次实际 worker 尝试；旧失败第 9 条的
四次已结算 mock 生成另计，不能把成功集合的 96 次当成全部实际成本。
所有成功位置都需按各自实际绑定重新审计；新旧 SQL 在独立验收前后必须一致。

完整组合审计、新旧适用源码差分、A0/A1 适用证据和当前工程检查完成后，
才可签发带 `COMPOSED_CPU_COMPLETION` 保证说明的功能 Gate A。
原单实例 `K3_FUNCTIONAL_REPLAY_PASS` 审计脚本不用于这份组合证书。
后续 B–E 仍要完成实际矩阵；本修订本身不是 Gate A 或研究完成。
