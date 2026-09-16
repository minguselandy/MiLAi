# V0224 执行范围代理审查

日期：2026-09-13。审查者：Codex subagent `/root/gate_review`，由主执行 agent 分派。此记录是依用户指令进行的代理审查，不是真人批准、独立机构审查或技术 PASS 证书。

用户本次指令要求详细阅读并执行 V0224 全部任务，遇到问题反思修改，人工授权、批准、审查和标注由 subagent 替代。该最新指令覆盖 V0223/V0224 编写时的“本次仅文档”“尚待执行指令”等历史执行限制；保留历史原文，不改写当时事实。它允许继续准备和提交有界后续子合同，不豁免技术前置门、保护池边界、服务边界、费用结算或证据真实性。

## 审读范围与证据

完整审读 [Lab 规则](../AGENTS.md)、[V0223 v0.1](../studies/active/MILA_V0223_准入成本分解与执行有效性恢复_GOAL_20260913.md)、[V0224 总 Goal](../studies/active/MILA_V0224_Gate_A至E执行有效性与持久记忆研究_总GOAL_20260913.md)。读取既有准备失败终态并定位执行入口、read scope、CPU guard 和旧观察器；没有读取保护任务正文，没有启动实验、访问 HTTP 或修改实现。

审读时 SHA256：

| 输入 | SHA256 |
| --- | --- |
| AGENTS.md | `023155bceb858f84e577776b86b6c6052858293a5d742fa93af0dcf62f26a57f` |
| V0223 v0.1 | `3f27a418cb112c480825022b7cd1d6e125f4da8c711465faf48925b64568d959` |
| V0224 v0.1 | `efc080216c2d1a102a89452dfb95831da854c83c1922c502f40ef7117ad9e4d0` |

[旧准备失败终态](/cra/memory/mx_memory/evidence/v0222-admission-offline/20260912-read-scope-r1/cpu-actual-outer-alWTyA/prepare-failure-terminal.json)保留 55 closed scopes，并把边界映射标为从源码顺序推断；不是 55 个独立测量样本。首条 P4 参考两个准入约 97.16 秒，旧 40 冷位置尚未完成。本审查没有重新计算真实闭包，不能据此填 K0 的精确规模。

## 当前可执行决定

**允许立即开展 K0 输入盘点与冻结、离线源码分析和局部实现准备。K0 完整冻结后，按 V0223 顺序进入 K1–K4。** 当前本记录不签发任何 Gate PASS，真实生成与 HTTP 分配仍为 0。

K0 至少补齐以下可核验内容才可运行计时实例：

1. 当前执行源码清单/hash、Python 与依赖版本、相对历史改动；不能仅用 Git HEAD，因为当前工作树有大量既有未提交/未追踪资产。
2. 57 ledgers 路径/hash/角色/事件行数/重叠；完整闭包唯一文件数、bytes、引用次数、JSON/JSONL 数量和行数。历史“5k+”不能替代复算。
3. 55 scopes 的逐边界映射、原 16+80 请求与 24 效果链、40 冷位置和顺序；动态 SQLite/事件初态、机械 ID 映射及负控时点。
4. 新 CPU-only 根、run ID、具体模式、完整起止点、所有内外层期限、固定 U/S 三对顺序与停止规则；不得续跑旧停止目录。

已有 [CPU guard](../tools/v0222_scoped_cpu_guard.py)是可复用的进程内 socket 拒绝路径，但源码自述它不防任意 native code 或未经批准子进程；每个实际入口/子进程仍须验证接线。已有 [observation](../tools/v0222_scoped_cpu_observation.py)使用 `sys.setprofile` 和 frame locals，**不可直接当 K1 新主测量器**。K1 必须关闭该 profiler，以粗粒度 spans 测量，不把旧探针比例折算成新成绩。

K1 的 S/U 中位数比必须 ≤1.10；真实输入/终态/覆盖一致且无缺失 end span。其后 55-scope 前缀仅是成本诊断。K2 每轮至多一个依据实测的通用候选，允许仅去观察器。候选若涉及跨准入 PASS 缓存、删除二次验证、改变动态权限或父审计责任，不能作为 v0.1 等价优化放行。

K3 必须完整 16+80 准备、24 效果链、实际 16+24 冷进程、父 finish/gate、独立 World 回读与新鲜动态负控；参考 Session 准入并集 ≤18 秒/总计 ≤60 秒，正式链准入 ≤90 秒/总计 ≤300 秒，CPU 阶段 ≤900/3600 秒。旧 3329 PASS 仅历史，当前执行 revision 需绑定规定五项工程检查的 terminal 证据。检查若需网络不能突破 A 零 HTTP。

## 后续条件范围

| 阶段 | 允许推进的条件与冻结缺项 |
| --- | --- |
| B | A 当前证书有效后，建立新 live scope，冻结既有 vLLM 服务、可见模型身份、生成参数、辅助 HTTP 上限、容量、截止时间、历史未知用量承接；16 次新生成，首遍全过才进入第二遍，16/16 完整意图判门。 |
| C | B 有效且兼容栈不变；冻结 24 链、每链最多 4 次、总上限 96、操作/回执/独立真值与未知提交恢复规则；24/24 才通过。 |
| D | C 后先记录 D0 去 Oracle 差异、完整自然输入与新增 Schema 校准；D1 上限 16 链/80 次，D2 上限 16 episodes/256 次；明确阶段期限与辅助 HTTP 上限。至少两 roots/两 families 各自 D1 合格且 D2 4/4。 |
| E | 每根 D 合格，公开 Note pin/冷读/隔离/实际呈现先成立；冻结 t0 与未来事件、M0 顺序、t0 标注准则和 agent 标注者身份。最多 4A+24B/448 次；满足首波有效性即完整复验，不因结果不利跳过。 |

表中调用数来自总 Goal 的计划上界，**本审查没有将其转换为已发放 live allocation**。主执行 agent 应提交填实的阶段合同，由代理审查根据用户持续授权进行有界释放；无需因旧文档写“人工”而停止等待真人。任何新的未知用量立即停止相应批，不能自动重试。新机制、新服务、保护池、默认 Product/部署或扩展 Schema 不在上述普通执行范围中。

## 反思与完成判据

允许在失败后继续有证据的修订；一个正式实例停止须保留终态与 NOT_RUN，下一轮新版本说明差异、资源上限和最小受影响重验。不得通过重抽 seed、补失败位置、加时或跨版本拼接构造 PASS。连续两轮无可区分证据应做设计复审。

代理可替代人工流程与离线标注角色，但不能虚构 t0 支持、冷读、模型实际看见 Note、业务效果或独立审查结果。审查人必须记录代理身份、输入依据和不确定性。只有当前 A–E 有效证书、合格 N0/N1/R1 首波与应触发复验、全分母/成本和综合研究反思齐备，才能签 `COMPLETE_WITH_BOUNDED_RESEARCH_CONCLUSION`；工程完成或失败报告均不等于总 Goal 完成。

本记录结论：`EXECUTION_SCOPE_REVIEWED_BY_SUBAGENT / K0_FREEZE_REQUIRED / NO_GATE_CERTIFICATE_ISSUED`。

## K0 输入清单独立复核

同日后续复核 [input inventory](/cra/memory/mx_memory/evidence/v0224/20260913-a-k0/input-inventory.json)，原始逐文件结果与复算依据保存在 [independent review](/cra/memory/mx_memory/evidence/v0224/20260913-a-k0/independent-inventory-review.json)，可由同目录 `independent_inventory_review.py` 重做。本次使用独立文件读取和 SHA256，没有执行原 inventory 脚本或计时实验，也没有展示原任务/来源正文。

- 清单 6491 个唯一路径全部重新读/hash/bytes 一致，总计 350728694 bytes，无重复路径或不匹配。
- 57 个 ledger 独立重读，逐非空行 JSON 可解析，共 225 行，hash/bytes/行数全部一致；这里只核验行与字节，不以此代替历史 FSM 或费用重建。
- 既有矩阵 4 roots × full/finish × 2 cold = 16 P3；4 roots × 3 kinds × 2 cold = 24 P4，各位置唯一。P4 中 16 链一写、8 链两写；源码 `ReferenceProvider` 每链在写动作后追加 READBACK 和 FINISH，故参考请求为 16×3+8×4=80，另 P3 每位置一份参考，共 16。此为冻结机械路径复算，不是已经完成参考或冷执行。
- 137558 引用可由清单 first_reads+repeat_references 复算；5277 次 JSON 解析和引用执行次数未独立重放，保持“原 inventory 报告的工作量”口径。

**限制影响 K0 准入：** 此清单来自 `verify_lineage`、`read_inventory`、旧 CPU binding 与 `verify_manifest` 的合并读取，再加 ledger 行盘点。它不是某个实际 `_authorize` 的完整闭包，也不是旧 55 scopes 的逐 scope 工作量。实际 `_authorize` 还验证 authorization/grant、当下期限、内存绑定与 `_validate_plan`；活动 SQL、ownership/stop/事务与收口检查也不能由静态清单证明。6491 files/137558 references 只能描述此合并清单，不能当作 K1 已精确复现真实两次准入的证据。

后续仍需冻结新实例的逐调用边界实际闭包、当前授权/动态初态、必要源码增量与机械 ID 映射，保留旧 55 scopes 为源码推导的失败前缀。结论：`LISTED_BYTES_AND_LEDGER_COUNTS_VERIFIED_NOT_FULL_K0`，未签发 K0 完整冻结或 Gate A PASS。

## K1 fixture 源码审查与局部修复

审查新增 `v0223_cpu_batch.py` 与 `prepare_v0223_measurement_fixture.py`，未启动 fixture。OfflineBatch 构造/授权路径与旧类经 AST 对比仅改变固定 root 选择，动态方法仍同一继承函数；这是源码局部证据，不等于实际全闭包准入等价。

发现并修复两个具体缺口：新 fixture 原先先 `seal()` 写目录后才间接核验 canonical root；现于读取/写入前及 seal 前拒绝父 symlink、已有/残留目录。原先 `scope.close()` 后 seal 重新计算 hash，缺少原 seal 工具已有的 input/source pins 对比，可能把两次观察之间变化重新封为合法输入；现将完整 inputs/source pins 纳入 scope 初读/关闭并在 seal 后精确比较，漂移即拒绝。失败后保留部分目录，禁止同 ID 重试。仍不声称可以防御有权限的其他进程任意时刻替换父路径。

新增 `run_v0223_admission_pair.py` 到 fixture 源码 entries，随依赖闭包封存。此条只保证纳入 hash，不是 worker 行为或外层期限的审查通过。历史 engineering artifact 仅保留相同动态读取负担，继承 gate 依然识别旧 PASS 标记，因此它绝不可作为当前工程认证或 K3 seal；后续当前证书必须另行取得。

局部验证：在 Lab 运行 `uv run --offline pytest tests/unit/test_v0223_cpu_batch.py tests/unit/test_v0223_measurement_fixture.py -q`，11 passed；新增反例覆盖父 symlink 无外写、部分 fixture 不可复用、scope→seal 输入/源码漂移拒绝。两份修改文件 Ruff check 通过，格式已修正。首次在工作区上层运行同命令因无 pytest 环境退出 2；随后切换 Lab 正确环境取得 terminal，未将环境错误当测试结果。该 fixture 尚未实跑，完整 K0、计时、动态负控和 K3 均未由这些局部检查证明。

## 负控计划与父进程记录审查

[negative-control-plan.json](/cra/memory/mx_memory/evidence/v0224/20260913-a-k0/negative-control-plan.json)逐项覆盖 V0223 §5 的八类负控，定位 34 个既有测试节点，附文件/函数 hash、断言的异常期待、注入边界、执行阶段与缺项。仅作源码核对，全部标 `NOT_RUN_THIS_REVIEW`。需要进一步证明的内容包括：遗漏必需依赖边而非仅引用不存在文件、重复 receipt 的独立效果计数、rollback 失败首因、活动 SQL 每边界变异、新 V0223 所有入口 guard、原/候选真实负担差分。已有测试名称和既有成功历史不能填成当前 A1/A2 PASS。

父进程 `run_v0223_calibration.py` 保留固定六位置和每子进程 300 秒上限，沿用只清理自有子进程的 manager。发现成功退出后损坏 JSON/缺失字段会跳过 terminal 落盘，且仅 PID 核验不能绑定 mode/合同。已修为逐位置读取/验收异常保存具体失败、实际 exit 与余下 NOT_RUN；读取原始 result 的同一 bytes 计算 hash，核对 worker-start 的 PID/mode/合同和 result PID，拒绝 `MEASUREMENT_STOP`/`NOT_READY_FOR_K1`。只生成观测终态，不签 K1/Gate A PASS；终态报告和父退出开销仍需外层生命周期记录。

验证 `uv run --offline pytest tests/unit/test_v0223_calibration.py -q`：9 passed，含损坏 JSON 的父终态/NOT_RUN 反例；Ruff check 通过。测试全部本地合成证据，没有启动实际六进程校准。当前 worker/helper 的实际 Session 路径另由另一代理审查，此记录不为其背书。
