# V0222 执行状态与收敛门

更新时间：2026-09-12 23:18（Asia/Shanghai）。本页维护当前状态，不追加执行流水账。
原 [Goal](MILA_V0222_解码语义与意图保真改进_GOAL_20260911.md)、实施记录和已停止批次作为历史保留；
历史文件中的“未执行／运行中”只代表各自记录时点。本页不替代原始验收、账本或具体实例授权。

## CURRENT STATUS

`EXECUTION_VALIDITY_INFRA_TOO_HEAVY / GATE_A_NOT_PASSED / MEMORY_NOT_ADMITTED`

当前 **Gate A — Offline closure** 未通过；固定计量执行方案已因实际准备时限失败关闭。
停止横向新增 adapter、缓存或审计抽象；不再调 B1/D11，不开发 State，不开放确认池。
用户已授权精确清理原测试进程；旧失败保留，新全回归已正常退出：3291 PASS／1 optional skip、exit 0。
上述579文件版本是计量接入前基线。当前581文件计量版本的唯一全回归14007已正常退出：
3329 PASS／1 optional skip、exit 0；六项同版工程终态与126依赖复核通过。
CPU-only seal/init已exit0；参考准备80010已exit1（`4aa787`），原PID1507400及time父进程均已消失。
16个P3离线参考完成；首条P4参考在原60秒Session期限处、首次生成前停止，0完成轮次。
首次生成前两次准入分别48.553/48.608秒，合计97.161秒；独立只读复核支持限定基础设施失败分类。
实际40冷进程、完整阶段计量和量化余量均未取得，不借此推断正式P3/P4总耗时。
新增模型／vLLM HTTP请求及GPU／服务操作均为0；原失败证据、计量和stop保留，不重跑、不加缓存、不延长时限。

## PASSED GATES

| 已有证据 | 可保留的结论 | 不能替代 |
| --- | --- | --- |
| [P1 字符串诊断](MILA_V0222_P1_STRING_DIAGNOSTIC_20260911.md)：D00/D10/D01/D11 = 0/6、2/6、0/6、6/6 | D11 是该小型诊断唯一合格候选；P2 后续兼容接线已审查 | 完整动作意图、执行能力 |
| [边界诊断](MILA_V0222_BOUNDARY_DIAGNOSTIC_20260912.md)：B0 4/8、B1 8/8，独立结果审查 PASS | 呈现／意图边界组合存在重复信号 | role、距离、模板的独立归因；Memory 效果 |
| [执行接线](../../docs/V0222_SCOPED_EXECUTION_WIRING_20260912.md)：3097 PASS／1 skip，完整 Mock 16→24 原文审查通过 | 该历史源码版本的工程与模拟接线证据 | 新增 CPU 代码全回归、40 个真实冷进程、vLLM 能力 |
| [CPU 入口](../../docs/V0222_SCOPED_CPU_REPLAY_IMPLEMENTATION_20260912.md)：当前230组件已纳入3330项全回归；3329 PASS／1 optional skip、126依赖条件审查 | 当前计量版六项工程终态及实现闭包证据 | 具体 CPU scope、实际规模计时、真实发送许可 |

上述 PASS 不合并为一个完整执行门，也不将不同版本的测试数相加。

## FAILED / STOPPED GATES

| 正式实例 | 实际终态 | 后续边界 |
| --- | --- | --- |
| [早期完整保真门](MILA_V0222_FULL_FIDELITY_RESULT_20260911.md) | 首个 P3 Schema 合法，但 S01 ≠ 授权的 manager_report | 永久停止；15 P3／24 P4 未运行 |
| [B1＋D11 呈现完整门](MILA_V0222_PRESENTATION_FULL_GATE_20260912.md) | 12 个正式 P3 PASS；第 13 个在 P3 总阶段 1800 秒处 `EPISODE_DEADLINE` | 永久停止；3 P3／24 P4 未运行；终审通过不等于门通过 |

第 13 个请求 HTTP 200、26739 raw 已结算；在完整 Schema 后的 `batch.admit` 截止，未完成期限内原验收与 release。
事后独立检查其完整意图通过，但**不能补写原 PASS**。这次停止不是新增已证实的语义错误；
[历史计时元数据复核](/cra/memory/mx_memory/evidence/v0222-admission-offline/20260912-read-scope-r1/historical-presentation-p3-timing-observation.json)
确认13次生成HTTP合计88.238秒，worker内全部52次HTTP切片合计89.922秒，13份exit墙钟合计1556.156秒。
差额1466.234秒只能叫未分项墙钟，不是CPU计时；父进程准入、finish/gate等也不在exit区间内。
阶段外预检36次HTTP另计1.987秒，不能当作完整预检时间。USAGE_KNOWN计时与生成HTTP重叠，禁止相加。
该观测191项证据hash复核一致，SHA `1c9ec0e2f48dca94fdb33cf320ab1b0c0e49d911ec5ad65b8796b4e520a31db0`；
它只为后续余量计算提供历史依据，不预测未运行3P3／24P4，不是新余量或Gate A通过。

历史 58 次生成、1081429 已知 raw 及唯一旧未知预约 28284 原样承接；实际总量仍未知。
预约不算实际费用，中央／地方镜像不重复计费；本轮没有新增实验费用。

## CURRENT IMPLEMENTATION VERSION

沿用 **B1 presentation＋D11**、现有显式 read-scope／evidence R2／history／Batch V2 执行接线、
CPU seal R3、固定 Mock/guarded 入口及最小只读计量。准入依据是源码 hash 闭包，不是名称或累计测试数。

本轮只读复核：

- [当前计量版启动记录](/cra/memory/mx_memory/evidence/v0222-admission-offline/20260912-read-scope-r1/cpu-measured-full-ZLK9pu/start.json)绑定 **581** 个当前文件。
  相对已通过的579文件基线，新增observer与测试，仅5个bootstrap、seal测试入口清单、2个AST期望共8个旧文件变化。
  reader/evidence、原CPU worker/runner及全部业务准入函数未修改；native MCP修复仍为 `83b77bddf64b8676d0e0101b9dcb72f24e6927e3c64b4c73f109c0754848e08f`。
- [当前计量版条件审查](/cra/memory/mx_memory/evidence/v0222-admission-offline/20260912-read-scope-r1/independent-scoped-cpu-measured-implementation-review.json)覆盖 **126** 依赖，SHA `2c73fc3cc7fbbd7b9654c0f65846b54c0edb2e5caabe92da9f88ba8d009a37e4`。
  独立审查确认旧116项未变、8项仅声明差异、仅新增2项，无删除；旧124项审查只作历史，不能递归借用为当前证明。
  当前56显式入口（5bootstrap、12测试/辅助、39包源码）；仍以六项同版工程终态通过为CPU准备先决条件，不是live授权。
- CPU 根 `evidence/v0222-scoped-cpu/20260912-cold-r1` 已停止；16 P3／24 P4全PENDING，未launch。
  stop为原具体原因 `REFERENCE_COMPLETE_INDEPENDENT_EFFECT_NOT_MET`，不改写SQL或恢复实例。
  拟定 live 根 `evidence/v0222-presentation-scoped/20260912-http-r1` 未创建。
- [原逐准入计量缺口](/cra/memory/mx_memory/evidence/v0222-admission-offline/20260912-read-scope-r1/scoped-cpu-measurement-gap-review.json)现有实现补齐，但实际规模完整覆盖尚未证明。

计量通过 `MILA_V0222_CPU_OBSERVE=1` 显式启用并由子进程继承；普通工程help/refusal默认不写计量。
回放必须另验每个实际进程完整report，关闭开关或只有 `OBSERVED` 不能满足Gate A。
仅对确切code object记录内存计数/时钟，保留生成器暂停期间归属与收口后期限/事务/停批完整span；
JSON文档loads和历史JSONL分列，父process CPU与独占子进程回收CPU分账，嵌套时间不相加。
单线程限制、profile丢失、未关闭scope均显式标不完整；报告最终写入CPU根旁的独立measurements目录。
子报告IO纳入原run_child墙钟，父报告/导入/进程退出仍须外层阶段墙钟覆盖，计量开销不扣除。

[当前组件终态](/cra/memory/mx_memory/evidence/v0222-admission-offline/20260912-read-scope-r1/cpu-observation-r1-BLOSG7/component-terminal.json)：
**230 PASS／0 skip，122.10秒，exit0**（88711／`0ece26`），581 pins无漂移；其中38项是新计量测试。
独立复跑38 PASS4.20秒（59177／`edd37a`），并复验关闭“未关闭scope被GC后ID复用丢记录”与“falsey异常类型误记null”两发现。
最终observer SHA `142f626d9828df0267b092414d6d5bda227229e2a207e81c12e23a81efbd24bc`。
旧R1源码保存在组件运行目录，SHA `cea133a144aa25c96480ec8bc5f5b9d9e4dc6057267f1617f1a719664964d4d1`；旧微基准不充当当前源码证明。

[当前小型开销观测](/cra/memory/mx_memory/evidence/v0222-admission-offline/20260912-read-scope-r1/cpu-observation-r2-RVa6bA/micro-overhead-result.json)
SHA `b081d461f2d4b5d2c6d6f335098690fdc428390657c1f78f5b8ed54cc41d328f`：每轮80合成文件、8 scopes，交替3对新进程。
读入/解析循环墙钟中位数0.1659→0.5262秒（3.17倍），含导入/报告/退出的子进程墙钟0.2400→0.6030秒（2.51倍）。
开销明显，必须留在原时限；这不是57历史账的真实文件闭包或40矩阵，不是余量预测、性能门失败或Gate A通过。

文件未变不是新的语义等价性证明；不以组件测试或父进程 cProfile 填补实际规模计量。

## CURRENT REGRESSION

`14007 / 3329_PASS_1_OPTIONAL_SKIP / EXIT_0 / 581_FILES_UNCHANGED`

计量版唯一新全回归 **14007** 已正常退出（terminal `d4d092`）；原runner **1266408**、uv **1267300**、pytest **1267307**均已消失。
实际收集 **3330** 项，**3329 passed, 1 skipped in 3922.67s**，跳过原因仅为optional Host SDK wheel。
[持久运行目录](/cra/memory/mx_memory/evidence/v0222-admission-offline/20260912-read-scope-r1/cpu-measured-full-ZLK9pu)
保存581文件启动闭包、其余5项工程exit0日志、进程记录、直接文件pytest日志、JUnit和exit.json。
启动记录SHA `7f622d903bb2a355218129dd0a9179b7b516b6a4225e1cb4373de6861ce9c4b9`；
显式短basetemp `/tmp/v22mf-etCZLR/tmp`；wrapper总墙钟3923.759秒，终态581 pins无漂移，不重复启动。
日志SHA `9d6d495f7d43f5c6e3a9e7334a8e6fd03aab2451050e0fcd6723c3111120fb4b`；
JUnit SHA `97a8be01a54d4094950121f1f668c327074c77c3205b9904b69ce7896a047514`。
独立解析3330个唯一case、0 failure/error；230 CPU组件（含38计量）、8 native MCP、3 V2集成均为子集，不能相加或当作实际40冷进程。
[当前计量版工程终态](/cra/memory/mx_memory/evidence/v0222-admission-offline/20260912-read-scope-r1/scoped-cpu-measured-engineering-terminal.json)
状态 `ENGINEERING_CHECKS_PASS`，SHA `dccca91bb144a774b849594022dc8af269a11b72fd8013847d44eb951d096cee`；581当前文件及13份工程制品全部重核一致。
终态核验脚本不启动测试，且已验证缺少exit.json时拒绝写PASS；旧579通过/旧失败均保留。

CPU seal/init唯一会话 **35601** 已exit0（`a2cbbc`），PID **1492809**已消失；显式设置 `MILA_V0222_CPU_OBSERVE=1`。
[外层原始日志及计时目录](/cra/memory/mx_memory/evidence/v0222-admission-offline/20260912-read-scope-r1/cpu-actual-outer-alWTyA)
使用GNU time覆盖整个入口进程的导入/报告IO/退出，墙钟与CPU显示分辨率0.01秒；CPU栏含回收子进程，不与observer父CPU混作同一口径。
[初始化终态及计量核验](/cra/memory/mx_memory/evidence/v0222-admission-offline/20260912-read-scope-r1/cpu-actual-outer-alWTyA/seal-terminal.json)：
外层墙钟198.85秒，user/system CPU194.87/6.65秒；observer窗口196.703秒，4个scope首次/收口完整，无errors/pending。
每个scope首次6363–6494个文件、约349–351MB，历史JSONL尝试445次；这是实际初始化观测，不是完整阶段预测。
绑定 `26c172febd8e982e0815b3bbc317d4d068307383797c3681e66e5d9a9ef38e8f`，126源码依赖、666封存输入。
完整参考准备唯一会话 **80010** 已exit1（`4aa787`），外层墙钟2764.39秒；user/system CPU2697.10/67.54秒。
[准备失败终态](/cra/memory/mx_memory/evidence/v0222-admission-offline/20260912-read-scope-r1/cpu-actual-outer-alWTyA/prepare-failure-terminal.json)
SHA `b9d5176ac20989788159e7a40a7bd9d7ac012eee84e24929c96fe0c4fae61430`；
[独立终态复核](/cra/memory/mx_memory/evidence/v0222-admission-offline/20260912-read-scope-r1/cpu-actual-outer-alWTyA/independent-preparation-failure-review.json)
支持 `EXECUTION_VALIDITY_INFRA_TOO_HEAVY`，明确限定 **REFERENCE_PREPARATION_60S_DEADLINE**。
prepare计量报告55个scope均完整收口、errors/pending空；`OBSERVED`只说明失败工作负载的计量完整，不是准备通过。
16个P3参考均有原验证文件；首条P4的Session结果为 `EPISODE_DEADLINE`、0 completed turns，未产生任何参考输出。
该World ledger/operations/dispatch均0；中央40位置全PENDING、events/claims/launch均0，仅engineering_checks已冻结。
原P4参考调用 `host.run(deadline=monotonic()+60)` 后，两次runtime准入的非重叠wall分别48.552988729/48.608391570秒；
合计97.161380299秒超过原60秒，随后首轮deadline检查拒绝。这是**离线参考Session时限**，不是HTTP60或正式每链300。
归属由冻结顺序与55 scope完整映射确定，Session起始未单独计span；未保存independent-effects细项，不追加业务失败断言。
无法从当前观测分离未计量成本与observer开销，也不能外推正式1800/7200秒阶段成本。
126源码及执行副本、666封存inputs和当前工程pins终态全部匹配；未修改业务准入或reader。
当前固定执行方案关闭：不重跑、不新增缓存、不放宽时限。具体scope、40冷回放、阶段余量及live均未准入。

### 已完成的计量前基线与旧失败

当前原会话已恢复，`write_stdin(67617)`取得完整测试摘要（`f08b82`）：
**1 failed, 3288 passed, 1 skipped in 4484.87s**；跳过原因是可选Host SDK wheel。
这更新先前另一会话的 `Unknown process id` 观察，不重启也未直接读取stdout pipe。
失败是 `test_v02_native_mcp.py::test_unix_mcp_hop_preserves_http_bytes_and_closes_connections`：
第71行直接使用151字节绝对Unix socket路径，报 `AF_UNIX path too long`。
生产connection使用fd-relative地址；此次没有证明relay、CPU准入或模型语义失败。

完整摘要已保存为[回归失败观察](/cra/memory/mx_memory/evidence/v0222-admission-offline/20260912-read-scope-r1/scoped-cpu-r3-regression-failure-observation.json)，
SHA `296fd060d8a5176a4d6b6f013ce42ea59b313287f7a90c7e1a08f6778f616bfc`。
用户明确回复“授权”后，重新核实PID身份，仅向pytest **2803200**发送SIGTERM，
父uv **2803193**随之退出，无需另发信号。原67617已取得退出码 **143**（`e01675`），
两个PID均不存在；这不是正常pytest退出或PASS。清理前579旧pins仍一致，证据未删除。
[精确授权清理记录](/cra/memory/mx_memory/evidence/v0222-admission-offline/20260912-read-scope-r1/cpu-r3-cleanup-authorized.json)
SHA `5b8dfe4f721659b0dcd63c8cd01308b2570f9dd244d1a495fdfef9e0f92e0aa7`。

独立subagent只读复核发现：测试在connect前启动非daemon `handle_request`线程，
异常会跳过后面的join。源码与残留poll/主线程futex等待符合测试清理未完成，
但未取得该活线程Python栈，不宣称已证明每个线程身份或死锁。

仅修订上述测试：客户端复用既有fd-relative地址；测试上游以finally shutdown/join清理，
普通/深路径均保留原HTTP字节断言，增加setup异常后的线程/连接收口负控。
显式长basetemp下 **8 PASS，1.66秒**（21971／`adfbb0`），独立只读审查通过。
[修复记录](/cra/memory/mx_memory/evidence/v0222-admission-offline/20260912-read-scope-r1/native-mcp-test-repair-observation.json)
保留“每次I/O超时不等于任意流量总耗时界限”的限制；不把局部8PASS补写为旧全仓PASS。

新全仓唯一会话 **70288** 已正常退出，terminal **98bfc2**、退出码 **0**，不再轮询或重启。
实际收集 **3292** 项，**3291 passed, 1 skipped in 3882.66s**；跳过项仍为可选Host SDK wheel。
使用独立短basetemp `/tmp/v22g-VzTUOF/tmp`；持久[运行目录](/cra/memory/mx_memory/evidence/v0222-admission-offline/20260912-read-scope-r1/cpu-r3-full-recheck-Ggd9vJ)
保存 `start.json`、`process.json`、直接文件日志 `pytest.log`、`junit.xml` 和 `exit.json`。
JUnit独立解析确认3292个唯一case、0 failure/error，覆盖192个CPU组件、8个native MCP、3个V2完整模拟集成测试；
这些覆盖数是3292的子集，不重复相加，也不代表实际40个冷进程。
进程已消失；wrapper总墙钟3883.810秒，运行期与终态后579新pins均匹配。
日志SHA `01f8edc91b642a72c2b6daf08d73cb278870f8050fcdc123fead304d8f20d3bb`，
JUnit SHA `0d6f0a8b4f8ae15f666825b1b6ef6626fc5ba26c17b0710afd5ce5b4538f6545`。

终态后边界检查、Ruff、Mypy（39个源码文件）、构建、`git diff --check` 再次全部exit0（37909／`ea2401`）。
[计量前工程终态记录](/cra/memory/mx_memory/evidence/v0222-admission-offline/20260912-read-scope-r1/scoped-cpu-r3-engineering-terminal.json)
状态 `ENGINEERING_CHECKS_PASS`，SHA `86db99f4388fd3588b0a753173037d9f792fd06f729c1119804d2f893dbf0c69`；
绑定579源码／配置／测试文件及12份运行与复核产物。该记录只覆盖计量接入之前的版本，
不得自动覆盖下一次入口修改，也不授予具体CPU scope或live发送许可。

## NEXT SINGLE GATE

**当前 Gate A 执行方案已停止；以下 B–E 保留条件路线，不是发送许可。任何新方案须用户明确新的调整范围，不能恢复已停实例。**

| 门 | 必需工作及通过标准 | 当前状态 |
| --- | --- | --- |
| **A：Offline closure** | 当前源码全回归 terminal PASS、其余工程检查终态和完整依赖 hash；既有准入／验收语义不变；实际规模 40 冷进程与逐准入计量完整；原阶段时限有量化 headroom | **NOT_PASSED / INFRA_TOO_HEAVY**：实际参考准备原60秒Session失败，当前方案关闭；40冷回放及正式阶段余量未取得 |
| **B：新 P3 full gate** | A 通过后，唯一新 concrete live scope 冻结并审查；同一正式实例完整 **16/16** intent fidelity PASS | NOT_TRIGGERED |
| **C：P4 known-intent execution** | B 通过后完整 **24/24**；目标、值、顺序、CAS、receipt、独立 World 回读及无重复副作用全部通过 | NOT_TRIGGERED |
| **D：自然任务能力** | C 后按独立合同完成 E1 恢复、E2 无旧 Note 任务；至少 2 root／2 family，每合格 root 两臂两冷遍 4/4 业务 PASS | NOT_TRIGGERED |
| **E：Memory 再准入** | 仅合格 root 进入 M0/M1；自然 Note 曾正确、冷持久与旧新双呈现可证实，再比较 N0/N1/R1 | NOT_TRIGGERED |

Gate A 的固定收口顺序：

1. **终态**：67617失败摘要、跳过原因、清理前579 pins及授权清理退出143均已取得。
   唯一新全回归70288的完整摘要、正常退出0与579新pins复核均已取得；不抹掉原次失败。
2. **计量准备**：只允许现有 CPU 入口最小只读计量补齐；不加新 reader/cache/admission 层，不改变被测函数语义。
   本轮已实施最小入口计量；唯一全仓14007终态3329 PASS／1 skip，581当前hash及126依赖重核通过，六项工程终态齐备。
3. **实际冷回放**：在既有 CPU-only scope 满足 seal 条件后，完整准备 16＋80 参考、40 独立 World、
   全部 57 历史账及真实文件闭包；原序 16 P3→条件 24 P4，40 个新 PID、退出后父 finish/gate。
   固定本地 Mock、网络拒绝 guard；不触达 vLLM/GPU，不用合成 history/PID 或缩小样本替代。
4. **完整耗时**：保存逐准入首次／收口 read、hash、bytes、JSON 与历史 JSONL parse，完整 worker、
   父 finish/gate 和阶段 wall-clock；父/子 CPU 分账，嵌套时间不相加；被杀进程缺失数据如实记缺失。
   计量和审计开销留在原期限内。冷进程不意味着清空 OS 缓存，不做硬件调优。
5. **余量与唯一范围**：在任何真实发送前冻结实测成本、HTTP 耗时/次数依据和余量算法；
   Mock 阶段耗时不是真实模型阶段预测，更不是 SLA。没有正的、可复算余量不准入。
   才可封存唯一新的 B/C scope、版本、矩阵、到期时间和审查；CPU 准备本身不授予 live 权限。

保持 P3 **1800 秒**、P4 **7200 秒**、每链 **300 秒**、HTTP **60 秒**及既有请求/顺序上界；
累计 raw-token 上限仍为 null。不得重置阶段时钟、排除审计耗时、补题、合并旧 12 PASS 或重试已停实例。

停止判据：

- 回归/记录/计量缺失：`GATE_A_INCOMPLETE`，不冒充性能失败。
- 实测既有执行栈无法满足原阶段时限或预先冻结的余量要求：`EXECUTION_VALIDITY_INFRA_TOO_HEAVY`，关闭本执行方案，不再新增一层缓存。
- 新 P3 任一完整保真失败：保留具体语义/协议原因并停止；超时、未知用量、审计失败另行分类，P4 不运行。
- P4 未满 24/24：已知意图执行仍未准入，E1/E2/M0/M1 不运行；不能靠增加机会获得“最终全绿”。

## MEMORY READMISSION STATUS

**MEMORY_NOT_ADMITTED**。即使未来 B/C 通过，也只得到 known-intent execution，不是自然任务或 Memory 能力。
详细 E1/E2/M0/M1 合同见[后续路线 §5–7](../../docs/V0222_后续执行与Memory再准入规划.md)。
只有旧 Note 当时正确、旧新材料实际呈现、执行链稳定，且有匹配 N0/R1 与跨 root 轨迹，才能讨论 Memory-use 因果。
N1/R1 均正确就保留普通 Note/复核；NO_WRITE 或呈现不足保留无效分母，不强造 Memory failure。
A0 默认、公网部署、权限及 Schema NO-GO 均不变；本阶段不重新讨论创新候选。
