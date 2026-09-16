# V0218 E0：首波强简单基线，保留全部尝试

状态：**WAVE_1_EXECUTED_AND_AUDITED / E0_IN_PROGRESS / WHOLE_GOAL_ACTIVE**。
T5 已签出限定适配 profile 的 G；这不是完整原生 benchmark 准入或整个 Goal 完成。
本波只有最初 2 个固定 D root，每个 1 个共同 A、Stable/Superseded × N0/N1/N2 的 6 个冷 B，
共 14 episodes。没有补题、重抽 Note、改失败世界或结果导向补跑。

## 冻结、边界与验收

Git 外证据：`evidence/v0218/20260911/e0-baseline-wave1-v1`。
源世界与 checker 与已签出 `t5-validation-v1` 完全一致；所有 12 根仍 EXPOSED_D，C=0。
本波 runner 的唯一实验能力扩展是正式 E0 三臂计划/同 A Note 复制/阶段账本与 T5 hash 验证，
Host/Provider/Memory 源码与有效 T3 协议逐字相同，没有改任务/工具动作/事件/笔记写作政策。

N1/N2 通过公开 Note CRUD 精确复制同一 A 最终版本并公开冷读；N2 只在 B system 追加原有通用提醒。
每个 B 世界保留相同 A 的普通业务记录、pending 和完整合法 history；不继承 A 消息。
实际 HTTP payload 核实共同 system、N2-only 提醒、旧 Note 字节与当前事实；不靠组装成功算呈现。
顺序固定为 `sha256('218:' + root + ':' + variant + ':' + arm)` 升序，各根各世界各臂一次。

预分配 14×16=224 请求，实际 122；兼容新请求=0。每请求输出 4096、60 秒，
每 episode 900 秒，整批 14400 秒，串行生成，raw cap=null，最后生成只可 finish，
此前保留行动机会；所有 FINISHED，包括用满 16 次的失败任务，不以 finish 文本判成功。
模型仍为本地 Qwen3.6-35B-A3B-FP8，temperature=0/seed=213，不承诺确定性输出。

Product 首次运行前独立 release lock 验证及实际安装 wheel 逐文件核验通过。
使用隔离 API/PG 和普通公开 Note 工具；结束 API stopped、compose stop=0，卷保留。
全局 Product 工作树 pin 漂移未修，不影响此次另行验证的不可变交付物；共享服务未调整。
T5 gate 当时 1173 passed / 1 optional SDK skip；E0 runner 变更后 1185 passed / 1 skip，
boundary、Ruff、mypy（39 文件）、build、diff check 均通过。

## 实际行为与分母

| 原始来源 / 世界 | N0 | N1 普通 Note | N2 同 Note + 一句提醒 |
| --- | --- | --- | --- |
| executive_assistant/task2 / Stable | PASS，5 请求 / 6678 raw | PASS，5 / 7251 | PASS，5 / 7386 |
| executive_assistant/task2 / Superseded | PASS，12 / 43101 | FAIL，8 / 15164 | PASS，11 / 36302 |
| insurance/task3 / Stable | PASS，7 / 10477 | PASS，7 / 10582 | PASS，7 / 10689 |
| insurance/task3 / Superseded | FAIL，16 / 36595 | FAIL，16 / 39553 | FAIL，6 / 8161 |

这张表按真实根/世界列出，不把 12 个 B 当 12 个独立 root。没有显著性、普适性或机制创新结论。
两个 A：日程 PASS、1 条自写 Note；理赔 FAIL、NO_WRITE。共 14 次尝试 9 PASS / 5 FAIL；
仅 B 为 8 PASS / 4 FAIL。两次 A 原始成本单列、不在总账反复计入各臂。

自主 Note 分母 A=2、自写=1、NO_WRITE=1；B=12，其中公开冷读旧 Note=4、
旧 Note 实际呈现=4、当前事实实际呈现=12、双呈现=4，全部双呈现来自同一个日程 lineage。
不能把理赔 N1 标签当作实际有旧 Note。B 的新自主保存行为另计，不回溯成为共享 A Note。
对应原始 `chain-audit-v1.json` 的各请求 ID/内容 SHA/HTTP 回执/冷 PID 可逐条追溯。

## Note 语义与轨迹复核

日程 A 的 Note SHA-256 为
`c51bac85ff14d03339dee1ef65c83ba19cba8a0d63a909a04effedcd77bdccd5`，
实际记载 C03 03-25 09:00–09:30/301/A，C04 03-26 13:00–13:30/302/A。
与该 A 真实业务记录及合法窗口一致；不套用旧 T3 批 C04=301 的不同 Note。
此为开发者逐段自审，不是独立专家/Judge；Note 未写时区，不冒充完整业务 schema。
更新事件随后令旧 C03 模式与 C04 时间/房间不再合法，充分当前事实在三臂均实际呈现。

- Stable 三臂均保留已有效的业务记录，没有无意义重写；各读取 current/policy/history/records 各一次。
  N1/N2 没省生成步数，Note/提醒增加本次输入成本；不据此推断所有 continuity 无益。
- 日程 Superseded：N0 的首次完整对象动作在 turn 6、全状态有效 turn 10；
  N2 分别为 turn 5/9（均从 0 计）。两者先改 C03，再改 C04，不要求唯一合法时段。
  两臂均曾提交过期整数 CAS，被拒后读取最新版本并真正修正，原错误请求保留。
- N1 在 turn 5/6 真实提交不必要澄清，并保留旧非法预约，最终 FAIL。
  它不是“发了新的错误预约”；是看见更新后未撤销/修正旧状态、执行了不必要暂停。
  该配对提供可研究的暴露差异，但样本极小、先前相同请求非确定性已知，不足以判定普遍 Note 因果效应。

理赔 A 错批 600，正确完整小时金额应为 400；这条错记录作为普通 A 业务状态由各 B 合法继承，
并非工作 Note。Stable 三臂都实际修成 400（首次完整动作 turn 5）。
Superseded 三臂均未完成当前应拒赔/0 元的状态，但失败层不同：

- N0/N1 各有 **10 个 INVALID_ACTION_ENVELOPE**：把来源字符串 `official-v2` 放入要求整数的
  `expected_version`。环境按合同拒绝，Host 每次真实呈现错误及整数 current_world_version。
  N1 两次拟提交的拒赔/0 元业务内容符合新事实，但错误版本类型令动作未执行；
  不能把这一现象描述为“模型始终不理解新事实”或把拟提交内容当真实成功。
- N2 使用合法版本提交不必要澄清，保留旧批准记录，属于业务判断/暂停错误。
- N0/N1 用满 16 次生成后 finish；既有技术反馈可见但未被用于正确动作。
  这是可恢复的 Agent 参数/行动失败，并非 transport 未发送、服务宕机或 checker 误判。
  如后续改善通用参数说明，须另冻共同 Host 版本并复跑共同 baseline，不在本批回改结果。

因此本波不能把理赔失败归因于持久 Note；N2 日程更新表现较好，也不能据此选定跨根强基线。
整个波中 3 次 VERSION_CONFLICT（A 日程一次、更新 N0/N2 各一次）已恢复；
20 次 envelope 拒绝保留为独立行动有效性诊断，不从全流程失败分母删除。

`baseline-audit-v1.json` 用冻结 checker 对每个实际动作后快照复算，记录目标完整与全状态完整
两个时点、精确重复写入、来源调用、原始成本及全因恢复轨迹。重复读取不自动等于“无必要”。
其分析程序在本波执行期间编写，指标定义来自先前 Goal，私有分析输出从未进入 Host；
不是新增盲审或用于回改世界/checker 的依据。
目前 B 实际错误对象后的当前事实/两行动机会分母为日程 N1 两对象、理赔 N2 一对象，均未恢复；
这是对象层描述，不是 3 个独立 root。继承 A 错误后直接修正另记；
“记忆诱发的恢复率”没有已证实因果分母，仍为 N/A，不报 0%。

## 成本、结论边界和后续

共同 A：17 requests / 26021 raw / 14.61 秒 episode 时间；
B：105 / 231939 / 126.34 秒；合计 **122 / 257960**，pending=0、violations=0、Judge=0。
生命周期口径可为每个 B 加同根 A 成本，但总账只收一次共同 A，不把配对复用当免费 A。
episode 时间不等同含服务启动/校验的整批墙钟时间；GPU 能耗、代理劳动价格未实测记 UNKNOWN。
全建设 + E0 首波累计 **332 requests / 642040 raw**；旧失败协议成本完整保留。

首波执行/呈现有效，观察到日程 Note 暴露差异及无 Note 时的理赔参数/业务错误；
没有确认 Memory-use 机制，也没有仅凭 N2 一次胜利选择最终 S*。
继续固定顺序的第 3–6 个 D root 强基线，再补 Helpful/适用范围/未决 probe。
E1 候选、E2 拆分/近邻、E3/E4 条件验证与必需 E5 尚未执行；
全 Goal 保持 active，本报告不是创新结论或终态收口。
