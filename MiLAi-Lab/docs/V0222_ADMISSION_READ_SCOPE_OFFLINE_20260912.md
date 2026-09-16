# V0222：单次读取作用域离线组件

日期：2026-09-12。状态：`OFFLINE_COMPONENT_AND_SCALE_REVIEW_PASS / COMPONENT_BASELINE_REGRESSION_PASS / NOT_CONNECTED_TO_BATCH`。
动机来自[完整门期限终态](../studies/active/MILA_V0222_PRESENTATION_FULL_GATE_20260912.md)：
12个位置正式通过，第13已收到合法输出与可信usage，但在共享1800秒截止前未完成原验收。
这是执行校验开销的工程问题，不是新的提示候选、模型额度或GPU诊断。

## 当前实际实现

仅新增[AdmissionReadScope](../tools/v0222_admission_read_scope.py)与
[合成局部测试](../tests/unit/test_v0222_admission_read_scope.py)，未修改旧冻结依赖或接线任何Batch。
作者`/root/batch_guard`；独立审查`/root/v222_review`；主代理复核文件hash。

- 显式作用域内，同一路径／期望SHA重复引用共享首次验证的bytes；JSON从同一bytes解析一次，返回深拷贝。
- 首次读取与收口分别执行真实内容SHA核验、regular-file和可观察路径身份检查；如实区分两次读取/hash计数。
- 期望hash冲突、读取／解析失败使整个作用域失效；即使调用者捕获错误，也不能正常收口。
- 收口仍遍历全部访问文件，保留原始异常并附加其他收口失败信息；关闭后不能复用。
- 规范化前拒绝任何`..`路径段，拒绝符号链接（含父目录别名），不静默改变请求路径的物理含义。
- strict JSON指原始UTF8字节、重复键和nonfinite拒绝；不额外承诺转义字符串为Unicode scalar，
  避免改变原证据读取的接受范围。业务呈现仍须由原更强合同单独验证。

组件自身不识别HTTP，也不是授权门。没有全局／跨作用域PASS缓存；未来调用方必须证明每次HTTP及事件准入
都创建、完成并销毁新的作用域，不能把一个ACTIVE对象跨请求保留或用空作用域冒充完整校验。

## 已复现并关闭的反例

1. 初版先abspath折叠`link/../file`，可能从另一实际文件取得预期hash并错报通过。
   已改为规范化前拒绝所有父级遍历，增加符号链接、缺失父段和普通目录三类负控。
2. 自定义异常的`__bool__`为False时，原异常虽已传播，status却会误报成功。
   已改为`is not None`判断，并覆盖body与解析两个失败路径。

最终同版46项局部测试由作者和独立审查分别运行通过（约0.10／0.09秒），Ruff检查通过。
首次历史41项和中间44项结果不替代最终46项；没有把小合成测试当完整规模时间证明。

| 文件 | SHA256 |
| --- | --- |
| helper | `7cdbabb997bfcef87715acac118d34385c610363ff342a90a37167badc15d147` |
| tests | `12cdfd14f71a37ee4986ad9f1fad1f307849ac024002ab9183406adbfd351d63` |

主代理全仓检查：边界PASS（chunk174293），Ruff PASS（d4e766），Mypy39源PASS（ffe354），
构建PASS（session73509 terminal1268b5）。`uv run pytest`原session6214已terminal exit0（a59979）：
2434 passed／1 optional Host SDK skip，1210.20秒；46组件测试包含其中。两个新文件在检查期间保持不变。
基线工程制品`engineering-checks.json` SHA256
`f0654d8052a53e7fc1081a22f38743761ea475785d9c03ced4453e6a7e1c5c7d`，位于下文外部制品目录。
该基线不覆盖随后开始的`v0222_scoped_evidence.py`适配层或其新测试，后续版本需另做回归。
旧P3独立终审5784项稳定依赖再次hash复核通过（session31231 terminaldd8c1c）。

## 必须保留的能力限度

这不是文件锁或不可变快照，只证明实际读到的两次内容及可观察身份符合要求。
独立审查构造过收口read返回旧bytes后立即同长度改写、且本环境mtime/ctime未变化的情况；
其后变化不保证被捕获。不能宣称所有并发中途修改必然拒绝，也不能靠第三次读取或忙等消除最终时刻窗口。
源码docstring已明确这一限制。未来若需要持续不可变性，必须单独定义并证明快照／所有权假设，
不能把元数据检查包装成与该更强性质等价。

当前没有新版授权／历史／artifact图验证器、动态SQL准入接线、冷runner或完整执行时间证明。
尤其动态stop、owner/PID、期限、中央地方费用镜像、唯一预约和阶段gate不能被此组件缓存或跳过。

## 实际文件规模观察与独立复算

已对旧冻结manifest代码60／inputs4486／scope-review5457／终审5784四份映射做零HTTP读取测试。
它们严格嵌套，共15787引用、898311847引用bytes；并集5784文件、331047898bytes，无hash冲突。
另读三个控制JSON后，仅终审文件为新增路径；实际5785首次与5785收口hash，每遍332178630bytes，
10005重复引用、3次JSON解析。主代理单次观测总墙钟3.22838秒、进程CPU3.22783秒。

独立代理进一步实际解析5266绑定JSON＋终审控制，共5267个JSON全部通过，收口重新hash通过；
该工作量总墙钟7.65397秒。两个时长来自不同工作量，不能视为速度复现或旧worker的加速比。
测试与原全仓pytest并行，未清缓存、未独占资源；没有动态SQL、完整history/tree语义、
冷worker、父审计/gate或16＋24完整阶段时间证明，也不推断未来JSON一定兼容。

外部制品目录：`/cra/memory/mx_memory/evidence/v0222-admission-offline/20260912-read-scope-r1/`。

| 制品 | SHA256 |
| --- | --- |
| scale-observation.json | `1bd83199f3ca7b2301632c9058ade3d8c0627726e3962527967441a2987db47a` |
| independent-scale-review.json | `32575c9bfce7519723450299033035bee8c92a4aa15b272b387d15567d719ce9` |

独立结果为`OFFLINE_SCALE_AND_JSON_COMPATIBILITY_REVIEW_PASS`，不是Batch或真实发送准入。

## 下一证据与权限边界

已形成[显式V2离线接线设计](V0222_SCOPED_ADMISSION_V2_DESIGN_OFFLINE_20260912.md)，
下一步实现内部读取接口并审阅去重前后检查覆盖与时间观察语义，再做零HTTP完整接线。
该设计已独立审查为`OFFLINE_DESIGN_REVIEW_PASS_IMPLEMENTATION_REQUIRED`，
外部`independent-design-review.json` SHA256
`21a1d0dda45dd9d3ab2ecc6ef36d7bd5a6395f96fe7ac022f2f626b90b9f8075`。
当前开始新增显式证据读取适配层及局部负控，未接入新Batch；旧helper及其46项测试继续保持稳定。
最新[适配层实施与反例](V0222_SCOPED_EVIDENCE_IMPLEMENTATION_20260912.md)：R1局部58项通过，
但实际引用树30秒未完成，且独审发现set子类可错误跳过子图；失败原文已保存。
R2窄修后64项局部测试及独审通过，四实际入口全部通过（完整树11.56秒），
新版全仓pytest session89818已2498PASS/1optional SDK skip（1209.05秒）；
后续[history实现](V0222_SCOPED_HISTORY_IMPLEMENTATION_20260912.md)另行验证，不以此放行Batch或模型阶段。
离线证明须覆盖原16＋24完整矩阵、冷进程、父审计与gate收口，并与实际冻结材料的文件数、字节量、
JSON大小和路径重叠规模相称；不得仅用41／46个小文件测试宣称能满足阶段时限。
旧实例已有60代码依赖、4486输入、5457范围审查依赖，最终审查5784稳定文件，可作为已暴露规模依据。
保留1800／7200阶段、300链、60HTTP上限；不以延长窗口、缩减矩阵或缓存上一请求PASS获得表面成功。

当前所有工程活动均为离线，没有新模型调用、GPU／驱动／容器／服务操作、凭据或保护池读取。
任何未来真实执行须另外冻结具体版本、历史账、范围和有效授权；本文件不授予新额度、不恢复旧批或放行P4。
E1/E2/M0/M1仍受原前置门约束，整体Goal保持执行中。
