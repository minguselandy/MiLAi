# V0222 意图呈现完整门：有界终态

日期：2026-09-12。状态：`FULL_STAGE_NOT_MET / EPISODE_DEADLINE / TERMINAL_REVIEW_PASS`。
完整费用与未运行ID见[结果JSON](MILA_V0222_PRESENTATION_RESULTS_20260912.json)；
离线实现、范围审查与时间风险记录见[实施报告](MILA_V0222_PRESENTATION_IMPLEMENTATION_20260912.md)。

## 实际结果

唯一B1＋D11实例`evidence/v0222-presentation/20260912-http-r1`已永久停止。
P3第一遍8/8通过，第二遍前4个通过，合计12个（full6、finish6）正式PASS。
第13个full因`EPISODE_DEADLINE`失败；余3个P3和全部24条P4未运行。
完整16门未满足，P4/E1/E2/M0/M1均NOT_TRIGGERED，Memory未准入。

原进程session35358以exit0结束（terminal chunk0e90c9），但runner结果明确为`FULL_STAGE_NOT_MET`；
进程退出码不等于实验通过。批结果SHA256：
`4ff2258fd19babc3dafbc74a94a1cc14b737700c132d583d33bb6fbe79a080ed`。

第13个worker deadline精确承接P3启动＋1800秒，而非独立耗尽300秒。
HTTP200、finish_reason=stop，网络耗时9.869秒，26739raw已结算。
原执行在完整Schema验证后的`batch.admit`处触发期限检查，尚未完成原严格CAS／意图验收与release。
Provider保存NOT_RELEASED_TO_EXECUTOR；父进程超时回收其子进程，exit -9。
独立事后核验该输出的严格JSON、完整Schema、严格整数CAS与完整placement_plan均通过，差异为空；
它仍未完成期限内原验收，不补原validation、修改FAIL或补成门PASS。

独立subagent审计`P3_RESULT_REVIEW_PASS`：12份正式PASS重建一致，13原始输出／费用、中央地方52事件、
13冷PID与退出、19冻结artifact及全部未运行位置复核。`P3-independent-review.json` SHA256：
`8b8e81caa0c094a5574e9c7bffd045d771e2e198854c08c499be5f64523164ec`。
主代理再次核验其5784项稳定依赖hash一致；中央SQLite/WAL/SHM没有绑定为稳定文件。
审计通过证明失败结果与账本可靠，不代表实验阶段通过，也不授予复跑权限。

## 费用与可观察耗时

实际13次生成：输入445675、输出4084、合计449759raw全部结算，新未知与费用违规均0。
45次tokenize＝P3预检32＋每次生成输入计数13；身份GET30＝预检前后4＋13冷进程各2。
共88次实际HTTP，全部200；最长生成9.869秒、tokenize0.218秒、身份GET0.046秒。
13个新冷进程、中央52事件；中央／地方完整镜像与最终原文独立审计均通过。

历史45请求／631670已知raw＋本批13请求／449759raw＝58请求／1081429已知raw。
唯一旧未知预约28284仍未结算，总实际为null；不把预约相加为成本。
Agent平台累计用量单列于实施记录，不与vLLM或Mock成本相加。

前两个成功worker总耗时119.328／116.010秒，计时HTTP仅6.327／3.424秒，非HTTP余量均约113秒。
非HTTP包含文件／JSON校验、启动、调度、IO等，不能全归为CPU，也不归为GPU问题。
重复授权、历史证据及artifact验证是静态定位到的主要待测路径；未在本批进行剖析压测或运行中修补。

## 后续边界

仅现有vLLM HTTP；无GPU／驱动／容器／服务操作、凭据读取、保护池开放、业务派发或Note。
已停批和旧冻结源码保持，不重试剩余位置，不换目录恢复额度，不运行P4。
[离线读取作用域组件](../../docs/V0222_ADMISSION_READ_SCOPE_OFFLINE_20260912.md)已完成46项局部测试和独立审查，
组件基线全仓pytest已2434 passed／1 optional skip（session6214 terminal a59979，1210.20秒），边界／Ruff／Mypy／构建通过。
后续证据适配层开始实施但不在该基线覆盖内。组件仅单次准入内消除重复读取／解析，收口重新核验全部内容；
不跨HTTP缓存PASS、不接线新Batch、不创建新模型实例，也不授予新发送权限。
未来接线须先通过完整规模零HTTP时间和安全证明，再单独核对新冻结范围与授权，不能靠延长时限通过。
两次读取并非不可变快照；元数据不可见的并发改写不保证被捕获。此限制和两个已修负控详见组件记录。

后续已完成组件实际规模观测与独立复算：5784文件／331047898bytes、15787总引用，
独立5267份JSON严格解析及收口hash通过。另有[显式V2接线设计](../../docs/V0222_SCOPED_ADMISSION_V2_DESIGN_OFFLINE_20260912.md)；
这些仍不含动态SQL、完整Batch、冷worker和父gate时间证明，不改变原P3终态或授予新额度。

四根E1公开事件草案已独立审阅，但具体动作依赖、可信覆盖关系及合法更新／澄清多解仍待解决。
不会为凑齐16链而预填真值、缩减root或打开新池。整体Goal保持执行中，未以本次有界终态替代完整目标。
