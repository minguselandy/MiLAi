# V0222：新版执行接线进度

状态：`BASELINE_REGRESSION_PASS / COMPLETE_MOCK_RAW_REVIEW_PASS / COLD_TIMING_PENDING / NO_NEW_LIVE_ADMISSION`。
承接[部分核心记录](V0222_SCOPED_BATCH_IMPLEMENTATION_20260912.md)与
[冻结 V2 设计](V0222_SCOPED_ADMISSION_V2_DESIGN_OFFLINE_20260912.md)。这是后续工程记录，
不修改旧正式实例、旧代码、旧失败或原 16 P3＋条件 24 P4、1800/7200/300/60 秒限制。

最新终态：session35677已3097 passed／1 optional SDK skip（3811.95秒，`f04027`），
559启动源码pin全保持，六项检查均通过；该基线不覆盖后来20份CPU源码/测试。
完整集成3测试及正负控原文独审已完成，区别于原作者99361缺失的临时原文证据。
正控归档SHA `68f0c253e89e5f30b1a17ade52d6cf895745a262c3a7d79f239a856ccff30b6f`，
独审 `independent-scoped-integration-positive-raw-review.json` SHA
`93cf53a4d6a78900031e52ff8e90a230ddab085b4c981b4b9b905110e9aac022`；
重建16P3＋24P4、96模拟生成、384事件、完整原文/意图/World回读和P3 gate。
两负控归档SHA `b58d62652d7e1541b7d3003f73b0cf08fdca439664e80e67080469aaa677e252`，
独审 `independent-scoped-integration-negative-raw-review.json` SHA
`f3403ad4839032f5fa0c6e29c9029518c4868b7d91848b163ab2f8fd804b5edd`；
分别保持错误意图停发和raw篡改拒绝，各1 FAIL／39 PENDING，没有P4或业务World。
全部制品位于external `evidence/v0222-admission-offline/20260912-read-scope-r1/`。

这些是合成history/public/PID与MockHTTP工程证据，不是40个真实OS worker或模型能力。
正控最初SQLite `mode=ro`观察创建了0字节WAL和32768字节SHM；归档3186原文件仍一致，无SQL数据写入，
不能声称文件系统零写入。后续只读方式及限制详见独审原记录。
当前CPU192项组件测试已通过，覆盖579当前文件的全仓session67617实际收集3290项运行中；
实际规模冷阶段计量和具体新实例范围尚未通过。以下旧检查点保留为历史，不覆盖本段最新状态。

## 已实现与证据范围

| 新版组件 | 当前证据 | 不能据此声称 |
| --- | --- | --- |
| claim 与原 Session 目录衔接 | 核心＋控制＋Session 70 项；claim 移至独立 claims 目录 | P4 完整模型门或真实冷进程 |
| 制品/准备/范围 gate R3 | 103 项及独审；完整 prepared、五制品与四控制文件闭包 | 具体新实例已获授权 |
| terminal 原文审计适配 | 87 项及独审；含原 Provider/Session/auditor 的 Mock 场景 | 自身证明 OS 子进程已退出 |
| 父 finish/P3 gate | 26 项；真实 SQL/scope，明确合成 `_audit` | 全部接线已通过原始审计 |
| HTTP/Transport | 61 项及独审；每请求新准入，单份镜像事件，迟到实际用量保留 | 真实 vLLM 或阶段性能通过 |
| Provider | 11 项及独审；八个验收方法保持原函数对象 | 新 Batch 全链已接通 |
| worker | 12 项及独审；错误/关闭首因保存，原主业务执行体不变 | 实际冷 OS/claim 或完整矩阵 |
| runner | 26 项及独审；模拟完整编排，另有三个真实短命 Python 子进程测试 | 真实新 Batch＋HTTP 全矩阵 |

主代理同版组合回归：**396 passed，73.00 秒**，session 30200，terminal `819615`。
范围是上述八组，未包含随后新增的 prepare/preflight 或完整集成测试；不是全仓回归。
原 core R1 全仓基线为 2707 passed／1 optional SDK skip（1233.87 秒），不外推覆盖后续代码。

新版 prepare 复用冻结完整材料生成器，以显式 facade 将每个准备 guard 接至新 `_operation`，
不替换旧模块全局变量。新 ID/scope 和 P4 initial hash 从固定旧 manifest/public bytes 派生，
其他资料、动作、顺序与验收不变。局部 11 passed（2.16 秒，84500／`db6d5f`），
其中矩阵派生读取实际已暴露固定输入，控制测试为合成夹具；不是完整参考生成或授权。

新版 preflight 已实现：所有 GET/POST 在 attempt 保存后完成独立 scope/SQL 准入；
每次核对五制品、四控制与范围审查，保留原 16/80 参考和 104/488 回执验收。
P4 preflight 必须在新 16 P3 和 P3 gate 后，不能提前做；不要求它自己的尚未生成 preflight 制品。
局部 39 passed（作者22.98秒；独立21.98秒，82430／`e03dac`），Ruff/format通过。
其来源重建、P3先决成绩与固定授权为显式合成；原收据审计和新SQL/scope检查真实执行。
准备与finish R3的同版独立组合另37PASS（25.88秒，37059／`e5efec`）。

## 已关闭的真实工程反例

1. 原新版 claim 在 Session 目录内提前建文件，导致原 fresh-directory 校验失败。修订只移动 claim，
   不放宽 Session 或删除已有证据；外部 claim/launch/exit 由 terminal adapter 显式核验和绑定。
2. gate R1/R2 缺少 scope 实例绑定、World/turn 完整读集或完整 prepared 关联。R3 在 freeze 和后续
   ready 两处核对当前完整依赖，独审 103 项通过，并检查旧完整准备结构相容。
3. runner 在 16 finish 后，若 P3 gate 和 stop 存储同时失败，可能因 rows=16、stop=null 误报 PASS。
   独立合成反例已复现；两条 PASS 分支现均要求 `error is None`，回归证明失败报告、无 gate、CLI=1。

这些反例保留为各自失败证据，不把局部修复后的测试数反写成旧实验成绩。

## 独立审查定位

原始记录均在外部目录 `evidence/v0222-admission-offline/20260912-read-scope-r1/`。

| 记录 | SHA256 |
| --- | --- |
| independent-presentation-gates-v2-r3-review.json | 96c2d89d9c1fa703014f9699ebb67603dc24c1a422ce0b85dd568d49f55c6dfc |
| independent-presentation-terminal-v2-review.json | cad8d1f893c55636697abb3287642b067e593d9274e4c5f7e752d4c3fe1edfb1 |
| independent-presentation-http-transport-v2-review.json | 6dd1d8f37cc5fd628aacbae6474ae604bcd29e72bea874a616219467da0a5c35 |
| independent-scoped-provider-v2-review.json | 22ee0a759bd2184d08a4cad3939f4d61bb75cc982ee225af553dccd410445e68 |
| independent-scoped-worker-v2-review.json | d8dabc51bf18e8ff383407a4ed84f4da85b775d70b0e01ba24182ed63c605402 |
| independent-scoped-runner-v2-review.json | d416a7856efd042a24d2e908e18db9745f196a3db2e351a986c8d41fadafae7e |
| independent-preparation-finish-r3-compatibility-review.json | 44fa9aeae2df98e053e94e684a6c5c2dfc7fd7d88b5212407497b35cb9e7705e |
| independent-scoped-preflight-v2-review.json | 460541e6fc082d4fea9274fce1d59d7ab57eb1f25ea0a8acb27ace42f5d8b536 |

主代理复核上述当前记录直接依赖 hash 通过（`f76e4e`）。旧
`independent-scoped-finish-review.json` 绑定 Gates R1 和旧合成 fixture；生产 finish 源码未变，
但两项依赖已更新，故它保留为历史限定审查，不冒充当前 R3 组合独审。
新的 preparation/finish R3 兼容审查直接绑定当前源码与 R3 gate，旧 R1 review 仅作历史观察，
不作为需要递归核对当前源码的依赖文件。

实际历史校验另做一次只读 CPU profile（89613／`90a2a7`）：5873固定文件，首次及收口各
344100625bytes、5275 JSON、130707重复引用，58请求/1081429 known和旧未知均保持。
带 profiler 墙钟29.376秒；verify_tree累计27.162秒、deepcopy累计8.763秒，累计时间相互包含。
该测量包含 profiler 开销，不能与之前12.980秒直接作速度对照，也不是整阶段时间通过。
外部记录 `scoped-lineage-cpu-profile-observation.json`，SHA
`142d9cd3a770b4f4d6404904592b6764836b310ba61c93e67d765f4618418be9`。

## 尚未完成与下一步

继续补新 prepare/preflight 负控，以及真实新版构造/授权/manifest/SQL/worker/父原文审计的
完整 **16 P3 → P3 gate → P4 preflight → 24 P4** Mock 接线，不用合成 PID 证明实际冷 OS 成本。
随后需要实际固定历史规模、完整冷 worker/父 finish/gate 的零 HTTP 时间观测；不能用单次 lineage
12.980 秒估算替代整阶段证据，也不预先宣称更快。

当前全仓 `uv run pytest` 已启动，session35677，collected3098（`8dd398`）；尚无终态。
开跑前559份Python/依赖配置hash已保存至外部 `scoped-execution-wiring-engineering-run-start.json`，
被测源码及新完整集成测试保持不变。边界（`e125a8`）、Ruff（`6a7fbf`）、Mypy39（`335b5d`）
和diff（`38d83a`）通过；构建session41575已terminal0（`22f89d`）。不得把运行中回归写成工程PASS。

完整新版集成作者session99361仍在运行。主代理对其临时数据库作一次只读快照（`741b01`）：
P3 16PASS、P3 gate及P4 preflight已登记；P4 9PASS／1RUNNING／14PENDING，无stop。
这是原文审计/父finish真实接线的Mock检查点，PID/HTTP/公开资料/固定历史选择仍为合成，
不能称完整24通过或实际模型结果；以原进程终态为准，不重启、不修改被测源码。

新版 seal 入口、完整工程终态与具体新实例冻结/范围审查仍待完成。拟定正式 root 未创建
（`f76e4e`），本轮真实生成/tokenize/身份 GET 均 0；不操作 GPU、设备、容器或服务，不读取凭据。
下载好的 benchmark 不重复下载，不开放保护池；Product/A0/State/Memory 不改动。
旧 12 PASS、第 13 FAIL 和未运行矩阵保持，E1/E2/M0/M1 仍依赖原前置门，整体 Goal 继续执行。

### 冷 OS 测量接口审查（规划，未实现）

独立 subagent `batch_guard` 只读审查确认：当前 Batch 构造、授权生成和 `_authorize` 固定正式ROOT，
worker/runner也绑定正式入口，不能直接用另一个离线目录运行原流程。不能为计时绕过构造、
改生产全局常量或创建正式实例。下一版本需显式、独立的 `CPU_MOCK_ONLY` root/合同入口；
它必须保留真实57账/四旧SQL、完整manifest/环境/动态检查，并与真实发送入口隔离。

拟测量保留四个实际已暴露公开root、完整16/80参考、40个真实OS子进程和原阶段/链时限；
MockTransport必须显式提供、禁止缺省联网，模拟回执保持完整原文长度并单独记账。
父准入、启动、执行、exit保存、finish及P3 gate都计入阶段，失败保留，不重试或延窗。
这仍只能证明实际历史规模下的冷OS＋Mock工程耗时，不包含vLLM网络/排队/推理时间，
不能直接签线上时限PASS。当前仅方案/接口缺口，完整Mock和正在运行的全仓源码不为此改动。

后续新增[CPU合同与网络守卫](V0222_SCOPED_CPU_REPLAY_IMPLEMENTATION_20260912.md)，17项局部通过；
不修改上述559份基线文件，尚未创建CPU实例或完成冷执行。独审已发现并保留注册钩子静默失败反例，
修复后仍需当前独审和完整CPU专用接线，不能把方案或组件当作阶段时间通过。

### 当前终态与证据保存缺口（追加）

完整新版Mock作者session99361已exit0：3PASS，2497.84秒（`0bdf33`），覆盖16P3→条件24P4、
首错停止费用保留、raw同向篡改拒绝。运行源码hash保持不变；合成历史/公开输入/PID/Mock限制不变。
但其 `/tmp/pytest-of-root/pytest-3104` 目录随后已不存在，独审无法再读取原始SQL/raw/World；
不能把作者测试终态升级为原文独审通过，目录丢失原因未逐事件鉴证。

主全仓35677仍在原PID2568150运行，其pytest-3105锁文件PID匹配，559被测文件hash保持。
对其完整矩阵DB只读快照（`94353a`）为P3 16PASS，P4 12PASS/1RUNNING/11PENDING，
P3gate/P4preflight已登记、224事件、无stop。这仍非终态。
后续先保留本次运行原始制品再做独立原文复算，避免默认临时目录清理后只剩测试日志。

[CPU专用接线](V0222_SCOPED_CPU_REPLAY_IMPLEMENTATION_20260912.md)新增固定Mock/worker、
准备/预检/父runner与独立bootstrap；合同/controls/worker/准备组合94PASS，另预检13、runner29
限定测试通过。CPU seal审查发现依赖集合闭包窗口，尚待修复与验证；没有初始化CPU或正式实例。
实际历史规模的40冷进程及原阶段时间仍未证明，不因新增入口而跳过真实完整门。

本次全仓的完整正例随后返回PASS（35677进度chunk `cc1a58`），其余两负控和全仓尚未终态。
主代理立即归档 `pytest-3105/test_complete_real_scoped_stac0` 全部原始制品，不删除原目录：
外部 `full-suite-35677-scoped-positive-raw.tar.gz`，SHA
`68f0c253e89e5f30b1a17ade52d6cf895745a262c3a7d79f239a856ccff30b6f`（3528文件/目录项）。
独立原文复算已交另一subagent，尚不预填通过。此为新的运行证据，不补造旧pytest-3104原文。

CPU seal后续R3显式纳入两个测试helper和39本地包源码，56项封存测试通过；当前CPU组件总192项，
其余工程命令通过，但包含CPU新增文件的完整全仓pytest仍待完成。具体CPU实例/阶段时间及真实门仍未建立。
