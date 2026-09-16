# V0222 实验报告：解码与意图呈现信号、执行准入失败

报告日期：2026-09-13（Asia/Shanghai）。实验覆盖 2026-09-11 至 2026-09-12 已保存终态；
2026-09-13 仅进行只读复核与报告编制，未运行新实验。

目标状态：**BLOCKED / 未完成**。
当前执行结论：`EXECUTION_VALIDITY_INFRA_TOO_HEAVY / GATE_A_NOT_PASSED / MEMORY_NOT_ADMITTED`。
研究类型：真实模型部分为 `RESEARCH_PROTOTYPE / INTENT_ORACLE`；后续离线部分为 `CPU_MOCK_ONLY`。
本报告不是 Product 效果报告、官方 benchmark 分数、新实验授权或完整 Goal 结项证明。

## 1. 核心结论

**V0222 找到了字符串约束和意图呈现两个有界信号，但仍未建立可靠的完整动作执行工作点。**

1. D11 在小型字符串诊断中达到 6/6；回到完整任务后仍选错合法目标，说明字符串兼容不等于意图保真。
2. 保持完整资料、目标值和 D11 不变，B1 为 8/8，B0 为 4/8；支持呈现／边界组合有影响，但不能拆分角色、距离、模板的独立作用。
3. B1＋D11 正式 P3 取得 12 个 PASS，第 13 个因整个 P3 阶段 1800 秒到期停止，未满足 16/16；真实 P4 没有运行。
4. 后续计量版工程回归 3329 PASS／1 skip；实际 CPU 参考准备却在首次生成前被准入耗时耗尽 60 秒 Session 期限，固定实例已停止。
5. 40 冷进程完整回放、正式阶段性能余量、known-intent execution、自然任务与 Memory 再准入均未成立。

因此，当前不是“Memory 机制无效”，也不是“普通 Note 已足够”的新证据；
**仍处在实验执行有效性校准阶段，没有本轮合格 Memory 消费因果分母。**

## 2. 研究问题与判定口径

本阶段旨在分开以下链路，而不是同时验证新的记忆机制：

```text
合法字符串生成 → 完整意图保真 → 合法动作执行 → 独立环境效果
                                               ↓
                                 自然任务能力 → 持久 Memory 消费
```

真实模型使用已记录的本地 vLLM HTTP，历史身份回执为 Qwen3.6-35B-A3B-FP8、
context 65536、可见 vLLM 版本 0.27.1；这些是运行时记录，不是本报告重新探测的服务状态。
没有通过直接 GPU、驱动或容器操作取得本轮结论。

- P1：三个合成夹具 × 四种 wire 条件 × 两遍，共 24 次；精确比较 JSON 解码后的字符串，不 trim、不归一化、不修补输出。
- 边界诊断：四个已暴露 root，B0/B1 两条件、两遍反序，共 16 次；不是 16 个独立任务。
- 完整 P3：四根 full/finish 两种完整合同、两遍，共 16 位置，须同一正式实例全部通过。
- P4：条件式 24 条已知意图执行链；只在完整 P3 通过后运行，不用模拟结果或旧 PASS 抵扣。
- 离线参考：16 个 P3 参考及 80 个 P4 请求参考、24 效果链；参考文件、正式位置和真实模型成绩分别计数。

累计 raw-token 上限为 null，不等于请求次数、期限、停止规则或授权范围无限。
详见 [原 Goal](MILA_V0222_解码语义与意图保真改进_GOAL_20260911.md)与[当前执行状态](MILA_V0222_EXECUTION_STATE_20260912.md)。

## 3. 真实模型实验结果

### 3.1 字符串约束诊断与 D11

| 条件 | 从 wire 解码约束中移出的规则 | 精确保真 | 严格 JSON／完整 Schema |
| --- | --- | ---: | ---: |
| D00 | 无 | 0/6 | 6/6 |
| D10 | 仅精确 `pattern` | 2/6 | 5/6 |
| D01 | 仅 `minLength=1` | 0/6 | 6/6 |
| D11 | 上述两项 | 6/6 | 6/6 |

D11 按发送前规则成为唯一兼容候选。P2 实现只延后指定节点的这两项解码规则，
完整权威 Schema 与后验验收保留；没有把目标值改成单字符，也没有放宽业务正确性。
P2 的完整 96 参考容量检查通过，冻结版本 1812 测试通过、1 项跳过。

这支持当前 HTTP 条件下的 wire 约束关联信号，不证明具体内部 decoder 根因或全部字符串语言兼容性。
随后首个完整 P3 返回合法 Schema 对象，但目标是 `S01`，不是授权的 `manager_report`；
1 次请求后永久停止，15 P3／24 P4 未运行，业务派发为 0。

来源：[P1 报告](MILA_V0222_P1_STRING_DIAGNOSTIC_20260911.md)、[P0–P4 结果](MILA_V0222_RESULTS_20260911.json)。

### 3.2 残余意图边界：B1 有信号

B0 保留原完整消息；B1 仅把最后 user JSON 中唯一的 `authorized_intent` 连同原值移成独立末尾 user 消息。
两臂不裁剪资料、不复制答案、不改变业务目标、Schema、D11 或生成参数。

| 原 root 序号／目标 | B0 两遍 | B1 两遍 | B0 主要偏差 |
| --- | ---: | ---: | --- |
| 1／manager_report | 0/2 | 2/2 | 选择 S01 |
| 3／manager_report | 0/2 | 2/2 | 选择 facts |
| 31／placement_plan | 2/2 | 2/2 | 无 |
| 56／triage | 2/2 | 2/2 | 无 |
| 合计 | **4/8** | **8/8** | 两根配对改善在反序复验中重复 |

16 次均通过严格 JSON 和完整 Schema。B1 每份输入增加 5 tokens，
但不能将这个小样本的输出长度差异解读为稳定节费收益。
这里测试的是给定正确意图的呈现，不是 Host 自主形成正确意图，更不是 Memory 调控。
结论保留为 `INTENT_BOUNDARY_SIGNAL`，无独立确认或因素拆解。

来源：[边界诊断](MILA_V0222_BOUNDARY_DIAGNOSTIC_20260912.md)、[逐位置结果与费用](MILA_V0222_BOUNDARY_RESULTS_20260912.json)。

### 3.3 B1＋D11 正式完整门：12 PASS，阶段期限停止

唯一正式呈现实例取得 **12 个 P3 PASS（full 6、finish 6）**。
第 13 个请求 HTTP 200、finish_reason=stop、26739 raw 已结算，但在完整 Schema 后的 `batch.admit` 处到期，
没有完成原期限内的 CAS／完整意图验收与 release；父进程超时回收 worker。

事后独立检查第 13 个输出的严格 JSON、Schema、CAS 和完整意图均通过，
**这不补写原 PASS，也不改变 12 PASS／1 停止／3 未运行的正式结果。**
全部 24 条真实 P4 均未运行。终审通过说明失败记录和费用可信，不是 full gate 通过。

| 历史计时区间 | 已核验墙钟 |
| --- | ---: |
| 13 次生成 HTTP 合计 | 88.238 秒 |
| 13 个 worker 内全部 52 次 HTTP 合计 | 89.922 秒 |
| 13 份 worker exit 墙钟合计 | 1556.156 秒 |
| exit 墙钟减其中 HTTP 切片 | 1466.234 秒，**未分项墙钟** |
| 阶段外预检的 36 次 HTTP | 1.987 秒，不是完整预检时间 |

HTTP 项存在包含关系，不能相加；未分项墙钟不是 CPU、hash 或 JSON 解析的单独耗时。
父准入、finish/gate 不在 worker exit 区间内；这组数据不能预测未运行位置或新的执行栈。

来源：[正式终态](MILA_V0222_PRESENTATION_FULL_GATE_20260912.md)、[结果 JSON](MILA_V0222_PRESENTATION_RESULTS_20260912.json)、
[历史计时复核](/cra/memory/mx_memory/evidence/v0222-admission-offline/20260912-read-scope-r1/historical-presentation-p3-timing-observation.json)。

## 4. 离线工程与实际准备失败

### 4.1 已完成的工程资产

现有实现包括单次准入内的显式 read-scope、收口重新核验、evidence/history 适配、
Batch/Provider/worker/父 runner 接线、独立原文/World 验收，以及固定 Mock 和网络拒绝 guard 的 CPU 入口。
历史账完整承接 57 份 ledger，动态停止、owner、版本、预约和事件镜像仍逐次核验。
这些是测试床资产，不是新 Memory 架构或 Product 默认能力。

| 回归版本 | 实际终态 | 解释 |
| --- | --- | --- |
| 67617，计量前原版本 | 3288 PASS／1 FAIL／1 skip；后经明确授权清理，退出 143 | 151 字节 Unix socket 测试路径报 `AF_UNIX path too long`；失败及清理保留 |
| 70288，测试修复后 | 3291 PASS／1 skip，3882.66 秒，正常 exit 0 | 测试复用已有 fd-relative 地址，补异常路径线程/连接清理；579 文件基线 |
| 14007，计量接入后 | **3329 PASS／1 skip，3922.67 秒，正常 exit 0** | 当前 581 文件版本；边界、Ruff、Mypy、构建和 diff 检查均有终态 |

最新 JUnit 的 3330 个唯一 case 中，230 个 CPU 组件（含 38 个计量测试）、
8 个 native MCP 测试及 3 个 V2 集成测试都是子集，不能重复相加。
常规全回归默认不开启整批 observation；专门计量测试和实际准备另有证据。
合成 Mock 的 16→24 接线不等于 40 个真实冷进程。

来源：[当前工程终态](/cra/memory/mx_memory/evidence/v0222-admission-offline/20260912-read-scope-r1/scoped-cpu-measured-engineering-terminal.json)、
[持久 JUnit](/cra/memory/mx_memory/evidence/v0222-admission-offline/20260912-read-scope-r1/cpu-measured-full-ZLK9pu/junit.xml)。

### 4.2 计量本身有开销，但实际工作负载中的占比未知

当前 observer 在 CPU 入口显式启用，使用 Python profiling 按确切 code object 记录计数和时钟，
覆盖 scope 首次/收口、operation、JSON/JSONL、父子进程；报告在进程结束时落盘，开销不从原期限中扣除。

小型对照每轮为 80 个合成文件、8 scopes，交替 3 对新进程：

| 中位数指标 | 无细粒度探针 | 启用当前探针 | 比值 |
| --- | ---: | ---: | ---: |
| 读入/解析循环墙钟 | 0.1659 秒 | 0.5262 秒 | 3.17× |
| 整个子进程墙钟（含导入/报告/退出） | 0.2400 秒 | 0.6030 秒 | 2.51× |

这是小型开销证据，不复制真实 57 历史账和完整文件闭包。
**不能用 3.17 或 2.51 去除实际准备时间，推断关闭探针后就能通过。**
冷进程也不代表 OS 页缓存被清空。

来源：[原始小型对照](</cra/memory/mx_memory/evidence/v0222-admission-offline/20260912-read-scope-r1/cpu-observation-r2-RVa6bA/micro-overhead-result.json>)。

### 4.3 实际规模准备：第一次参考 Session 尚未生成即超时

CPU-only 实例 `evidence/v0222-scoped-cpu/20260912-cold-r1` 已完成 seal/init，随后参考准备失败：

| 步骤 | 结果与实测 |
| --- | --- |
| seal/init | exit 0；外层墙钟 198.85 秒；4 个 scope 完整收口；126 源码依赖、666 封存输入 |
| 完整参考准备 | exit 1；外层墙钟 2764.39 秒；55 个 scope 收口完整；无 observer errors/pending |
| 已准备部分 | 16 个 P3 参考有原验证文件；P4 完成链为 0 |
| 首条 P4 参考 | Session `EPISODE_DEADLINE`、0 completed turns、无参考输出；World ledger/operations/dispatch 均为 0 |
| 停止状态 | SQL 原因 `REFERENCE_COMPLETE_INDEPENDENT_EFFECT_NOT_MET` 保留；16 P3＋24 P4 正式位置全 PENDING，未 launch |

首次生成前两次非重叠 runtime 准入分别为 **48.552989 秒、48.608392 秒**，
合计 **97.161380 秒**，超过原 **60 秒离线参考 Session** 期限。
归属依据是冻结代码顺序、完整 55 scope 映射及 Session 终态；Session 起点没有独立 span，不能夸大计时精度范围。
未保存独立效果细项，不追加业务失败判断。

这次停止是**实际计量执行方案的准备层基础设施失败**，不是模型生成、意图或 Memory 语义失败。
`OBSERVED` 表示失败工作负载计量完整，不表示工作负载通过。
40 冷进程矩阵没有执行，因此也不能断言新版正式 P3/P4 必然超时。

四种期限必须区分：离线参考 Session **60 秒**；单 HTTP **60 秒**；正式每链 **300 秒**；
正式 P3/P4 阶段分别 **1800/7200 秒**。本次命中的是第一种。

来源：[初始化终态](/cra/memory/mx_memory/evidence/v0222-admission-offline/20260912-read-scope-r1/cpu-actual-outer-alWTyA/seal-terminal.json)、
[准备失败终态](/cra/memory/mx_memory/evidence/v0222-admission-offline/20260912-read-scope-r1/cpu-actual-outer-alWTyA/prepare-failure-terminal.json)、
[原独立失败复核](/cra/memory/mx_memory/evidence/v0222-admission-offline/20260912-read-scope-r1/cpu-actual-outer-alWTyA/independent-preparation-failure-review.json)。

## 5. 请求与费用汇总

以下仅合并互不重叠的 V0222 **真实生成**，包含失败请求；离线 Mock 不按真实模型用量记账。

| 阶段 | 生成次数 | 输入 tokens | 输出 tokens | raw tokens |
| --- | ---: | ---: | ---: | ---: |
| P1 字符串诊断 | 24 | 4072 | 379 | 4451 |
| 早期完整 P3 | 1 | 27844 | 494 | 28338 |
| B0/B1 边界诊断 | 16 | 559228 | 9568 | 568796 |
| 呈现完整 P3 | 13 | 445675 | 4084 | 449759 |
| **V0222 合计** | **54** | **1036819** | **14525** | **1051344** |

54 次均结算，新未知为 0。另有 358 次 tokenize、128 次身份 GET；
三类合计 540 次 HTTP，不能把辅助请求当作 540 次模型生成。
后续 CPU-only 校准、参考准备及本次报告新增真实模型/vLLM HTTP 请求均为 0。

跨更早历史累计 58 次生成尝试，已知 raw 为 1081429；仍有唯一旧未知预约 28284，
**完整实际总量为 null/未知**。预约不是实际消费，也不能用旧已知数掩盖未知请求。
Judge、云端回退为 0；Agent 平台用量与 vLLM 实验用量分账。
本报告未取得可对齐的最终 Agent 累计终态，不把旧快照当最终值、不填 0，也不合并为总成本。
raw tokens 是用量记录，不是已计算的货币费用。

## 6. 准入状态与创新判断

| 层次 | 当前状态 | 尚缺的关键证据 |
| --- | --- | --- |
| 字符串／意图呈现诊断 | STRING_RULE_SIGNAL＋INTENT_BOUNDARY_SIGNAL | 外部泛化与独立因素归因未验证 |
| Gate A：离线执行有效性 | **NOT_PASSED / 当前方案已停止** | 成功的完整准备、40 实际冷进程、阶段与逐准入成本、量化余量 |
| Gate B：新 P3 | NOT_TRIGGERED | 同一新实例 16/16 完整意图 PASS |
| Gate C：真实 P4 | NOT_TRIGGERED | 24/24 正确目标/值/顺序/CAS/receipt/独立 World 效果、无重复副作用 |
| Gate D：E1/E2 | NOT_TRIGGERED | 恢复能力、无旧 Note 的自然业务能力，至少 2 root／2 family |
| Gate E：M0/M1 | MEMORY_NOT_ADMITTED | 自然正确旧 Note、冷持久、旧新双呈现、匹配 N0/N1/R1 行为 |

目前可保留的贡献是**执行混杂分层、严格失败保留、意图呈现诊断与可审计工程资产**。
它们不证明新的 Memory/State/注意力机制，不证明 ordinary review 已经解决所有自然任务，
也不构成正式 benchmark 贡献或论文级创新确认。

后续可能有价值的问题仍是执行仪器本身，而不是增加 State 字段：
多少成本来自原准入、多少来自细粒度观察、多少来自两者组合，目前尚未分离。

## 7. 限制与下一步边界

本轮使用少量已暴露夹具/root、重复固定条件，不能由命中比例估计总体准确率。
已知意图 Oracle 不等于自然任务；模拟 World 不等于公网产品效果；旧 Note/新证据的有效 Memory 对照尚未进入。
文件首次/收口两次核验不等于全过程不可变快照。

当前固定方案保持停止，Goal 阻塞、未完成；不重开旧批、不补未运行位置、不增加缓存或延长期限。
前一轮提出的“低开销边界计时＋计数器汇总”只是**待授权建议**，尚未实施或产生新结果。
若用户另行授权，应先冻结计量差异、保留/减少的观测粒度及语义不变量，开展有界零 HTTP 校准，
再决定是否建立一个新的 CPU 完整实例；不能把关闭 observer 直接当 Gate A 通过。
真实 P3/P4、E1/E2、Memory 研究仍须逐门重新准入。

A0 默认、Product 行为、公网部署、权限及 Schema NO-GO 不变；未读取凭据、开放保护池或运行新的 GPU/服务操作。

## 8. 本次报告复核范围

2026-09-13 编制时对已有记录进行只读复算，未重新执行工程全回归、模型实验或原审计程序：

| 复核对象 | 本次结果 |
| --- | --- |
| 当前工程终态引用文件 | 594/594 hash 匹配（581 源码/配置/测试＋13 工程制品） |
| 当前 CPU 实现审查依赖 | 126/126 hash 匹配 |
| 准备失败独立复核的直接证据 | 5/5 hash 匹配 |
| 历史 P3 计时元数据证据 | 191/191 hash 匹配 |
| 14007 exit 记录的日志/JUnit/start/process/other-checks | 5/5 hash 匹配，退出码 0 |
| 原 JUnit 重新解析 | 3330 唯一 case；3329 PASS、1 optional Host SDK skip，0 failure/error |
| 三批结果的用量相加 | 54 次生成、1051344 raw；输入＋输出一致，旧未知不并入 |

集合可能重叠，以上核验数量不相加为“独立证据总数”。本次没有重新审阅全部 54 份模型原文，
相应业务与呈现结论引用各批已保存的原始结果及当时独立审计；本次复算不另称一次全面独立审计。
原 Goal、停止实例、原始账本、失败结果和当前执行状态原文均保留，报告仅新增汇总并同步导航摘要。
