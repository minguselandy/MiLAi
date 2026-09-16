# V0222：独立 CPU 回放入口进度

状态：`COMPONENT_192_PASS / CURRENT_FULL_REGRESSION_RUNNING / COLD_REPLAY_NOT_RUN / NO_LIVE_AUTHORITY`。
承接[执行接线与冷进程方案](V0222_SCOPED_EXECUTION_WIRING_20260912.md)。完整 live 接线的
回归session35677已终态3097 PASS／1 skip；CPU新增20文件不在该559文件基线覆盖内。
覆盖当前579文件的新回归session67617已实际收集3290项，仍在同一进程运行，未记PASS。
以下历史检查点保留；最新工程状态以本文末节及紧凑结果为准。

新增 `v0222_scoped_cpu_batch.py`，显式 `OfflineBatch` 使用独立固定CPU_ROOT和CPU合同，
不修改现有live Batch或其固定正式ROOT，也不使用全局reader/常量替换或跳过正常构造。
构造和 `_authorize` 的全套scope、控制、真实lineage、manifest、环境、原矩阵及期限检查保留。
AST白名单对照仅允许根/CPU合同名与标识/守卫调用差异；动态SQL/FSM、claim、引用、验收和
父finish/gate等21项方法保持原函数对象。此适配有额外保护开销，不声称等同live构造成本。

CPU合同精确标明 `CPU_MOCK_ONLY`、真实HTTP/设备操作不允许、模拟费用不是实际费用。
原36小时授权窗口、P3/P4阶段1800/7200秒、链300秒、HTTP60秒和16＋24完整矩阵不放宽。
授权来源为离线工程请求，不复制原真实发送许可；纯构造函数不写任何授权文件。
尚未创建CPU_ROOT或正式ROOT，未读取凭据或调用GPU/共享服务。

新增 `v0222_scoped_cpu_guard.py`：只有显式开启才在当前新Python进程注册socket审计拒绝钩子，
导入本身无副作用。专用bootstrap必须在加载回放stack前启用，子进程必须各自启用；
默认httpx路径也会在socket事件前被拒。它不是对任意native代码或未批准外部子进程的安全沙箱。
完整worker仍须固定内部MockTransport，不能把guard当作允许缺省联网的理由。

独立审查发现R1的真实反例：已有audit hook可令 `sys.addaudithook` 静默拒绝注册，
但原代码仍误置ready。只在独立短命Python中创建/关闭socket证实，未connect或发送HTTP。
R1源码已在修改前保存，SHA `76cb6b20352d09e9e07fc861c4dc146661aeebef11f71627fca8eb990d5b2c13`；
发现记录 `scoped-cpu-guard-r1-independent-finding.json`，SHA
`97e19d5145e90ef9e646fb524f9194605af758fc92ab08cb7eb1cd3506c34582`。

R2在置ready前发送一个无socket的合成audit事件，仅捕获本次函数调用私有异常类型才认可注册。
静默拒绝时抛错、ready仍false。新增回归后主代理17PASS（6.54秒，21689／`e116da`），
Ruff/format通过；包括live/CPU根隔离、原限额、AST对照、真实短命进程默认httpx拒绝与注册拒绝。
R1的16PASS保留为不足以发现该漏洞的历史观察，不覆盖此修复。
R2独立17PASS（6.38秒，50842／`e94b0b`）、Ruff/format通过；另两个独立短命进程负控证明
同文本的无关异常不能伪造注册确认、实际live Transport缺省路径在合成admission下被guard拒绝。
后者不是完整OfflineBatch构造；16项bool/int/mode纯fingerprint比较也不是实际 `_authorize` 门测试。
独审 `independent-scoped-cpu-contract-r2-review.json`，SHA
`b4eb933213858ca91a93bf8e1b7f5bae19ddaa9562b65fa911d3ecd43058529d`，12直接依赖由主代理重核一致（`7c8795`）。

当前源码SHA：CPU Batch `186fe9f53bc1e60e93d407e3a7e2e48586b6c104f79497aadae92b1c8d6a13e5`；
guard `338972bec63c9fff56b87e2e0cd9a4daaf34aa20f8dcd01e4dd204d91e11bc14`；
测试 `72453e1ec49901b647de5251ae0dda54c3c00951e310899c1038ec6d2974fe4b`。

仍须完成CPU专用scope/参考准备、封存、Mock preflight/Provider入口、真实冷worker/runner及
完整实际历史规模测量。不能把17项合同/guard测试当作已构造真实CPU实例、完成40冷进程，
或证明1800/7200秒阶段、更不能替代真实vLLM输出及Memory前置门。

正在补独立CPU子进程内的真实constructor/control/manifest/plan负控（固定lineage和根选择为合成），
以实际拒绝路径补强上述AST/纯比较证据；不在pytest主进程安装不可移除的网络钩子。

本次边界（`08fdcc`）、Ruff/diff（`3476f8`）、Mypy39（`02a4b3`）和构建
（14698／`c64e48`）通过；17项为上述局部结果，不能把仍在运行且未收集CPU新增文件的
3098项全仓基线当作当前CPU版本的全仓终态。

## 后续入口实施与限定验证（追加）

CPU controls 的33项真实构造/授权负控已通过；它们在新guarded Python中使用合成根及历史，
没有替换 `_authorize`、manifest或原矩阵验证。正例仅初始化40PENDING，无launch/claim/event。
新增固定Mock、CPU Provider工厂及worker/guarded bootstrap，38项通过；worker.run完整AST与
live V2相同。脚本仅从完整冻结参考读取原文，每次生成消费一次匹配的tokenize输入；
100输入/20输出/120总量为模拟常数，绝非真实计数或费用。

独审复跑17＋33＋38＝88PASS（93.55秒，62762／`da52c0`），记录
`independent-scoped-cpu-controls-worker-review.json`，SHA
`e3f616f2b3620b230692ad12d0f578c3765fccf7355681a6f0aee15374a60d3f`；
主代理已核对其16个直接依赖（`3bc0ed`）。公共factory带实际preparedBatch的正例、完整成功
worker/Session及40真实冷进程均未由上述测试证明，仍须完整回放。

新增 [CPU参考准备](../tools/prepare_v0222_scoped_cpu.py)及独立bootstrap：复用同一完整materializer，
计划仅改CPU ID/scope及对应初始hash，不复用未来live实例的scope。原固定16＋24矩阵、全部业务值
和独立hash检查等6项PASS（8.52秒，1287／`1edb3b`）；这只读派生未创建实例。
主代理合同/controls/worker/准备组合94PASS（101.49秒，95342／`bac7cc`）。

新增 [CPU预检](../tools/preflight_v0222_scoped_cpu.py)及bootstrap，13项PASS
（10.69秒，60866／`c499de`）。完整AST仅允许无外部transport参数、guard、正常构造后固定Mock
三个差异；原16/80参考、104/488回执、1200/2400预检窗口、fresh admission和失败处理保留。
这些是绑定/拒绝测试，尚未实际跑完完整CPU预检，不代表HTTP tokenizer容量。

新增 [CPU父runner](../tools/v0222_scoped_cpu_runner.py)及bootstrap；子进程命令固定guarded worker，
原退出保存→父finish→PID核对→单次P3gate保持。结果使用 `CPU_REPLAY_*`，并显式标明零真实
HTTP/模型及模拟费用。独立实现审查方的29项runner测试＋上述6项准备测试通过
（18.16秒，80366／`4261e3`）；runner测试中的Batch/child为合成，不算真实40冷进程。

CPU seal入口已新增但尚未通过组件审查：要求完整当前源码的六项终态工程证据、独立CPU实现
审查、真实57历史与完整矩阵，初始化后仍需参考准备及具体scope审查。R1闭包缺口已复现：
封存第二次扫描依赖的缺失/增加都未被拒，原evidence.validate也接受，两个负控失败
（91464／`aa374b`，1.98秒）。仅为临时合成依赖扫描反例，不是真实实例违规。
原完整源码修改前保存至外部 `scoped-cpu-seal-r1-source.py`，SHA
`89aee1facaa27127a6aca64f84d6d170b072fdcbb7ccdc85ef4edb5f0c5c7611`。
R2要求manifest.dependencies精确等于scope内已审核的source pins，在authorization/binding及
初始化之前拒绝集合或hash变化；SHA `04439cb1c2b0ee6a5204311e2dbeb29318c1fca433c43c9c8f143cf14f4b2239`。
R2扩展回归45PASS（8.71秒，88900／`2bee3f`），主代理另复跑45PASS
（8.78秒，80076／`b55b34`）。独立源码审查方编写这些合成测试；真实scope/依赖扫描/副本校验
与guard负控保留，但历史/授权/最后Batch初始化为明确fixture，不是实际57账实例。
限定记录 `independent-scoped-cpu-seal-component-review.json`，SHA
`4135bd4ae188a11179a443c88f8249529549db73995526cdae6cc82af761830a`，7直接依赖重核通过
（`df3c6a`）。组件无未修阻断，不等于整套实现或具体scope许可，当前仍未启动实例。

预检/runner主代理组合42PASS（19.21秒，41254／`306c18`）。入口限定独审记录
`independent-scoped-cpu-entrypoints-review.json`，SHA
`0dbfbccb90ed246b8eff7287654a4070cc92767052057c237fe8821201130e2c`，20静态依赖已重核
（`b71e61`）。其中独立CPU预检13PASS/10.79秒；runner29是实现独立审查方编写的测试，
不能称独立于该测试作者的再审。seal及实际40冷矩阵不在此记录准入范围。

全仓35677仍运行，已有559源码hash全部不变（`742fdb`）；以上新增CPU文件均不在其收集范围。
CPU_ROOT和拟定live ROOT均未创建（`cd6676`），本次真实HTTP/生成/GPU操作均0。

当前七组组件共181项（主代理分94/42/45三个命令运行），20个CPU源码/测试hash固定。
外部记录 `scoped-cpu-entrypoint-components-r2-engineering.json`，SHA
`d3014636259f1fdfeb8d4bd10c257bebbcc424ee7cd88753531669c740ebcffe`。
边界（`8de7db`）、全src/tests/tools Ruff（`d624f6`）、Mypy39（`9b5d1e`）、diff（`aac5c4`）
及构建（38508／`dbae8a`）通过；当前CPU源码的完整全仓pytest尚缺，不能把此记录当作seal
要求的六项 `ENGINEERING_CHECKS_PASS`。下一步保留完整集成原文、完成当前工程/整套范围审查，
再初始化CPU实例并执行真实准备、完整预检和40冷进程；完整时间与真实模型门仍未证明。

### R3：显式绑定本地包和测试辅助文件

整套只读审查发现旧tools-only依赖算法不会递归两个测试helper及本地包导入。
83项工具闭包中，`check_v0210_control.py` 引用 `milai_lab.methods.state_control`，
`run_v02_memory_flow.py` 引用 `milai_lab.product_adapter.manifest`；两个包还有包初始化依赖。
CPU controls和runner分别引用未列入原entries的两个fixture模块。

R3不改冻结依赖算法，改CPU专用 `_entries()`：两份helper和全部39份 `src/milai_lab/**/*.py`
显式作为源码封存并写executed-source，不只靠review顺带提供inputs hash。
缺包/缺__init__、工程或审查任一遗漏包/helper pin均拒绝；R2二次集合精确比对保留。
R2源码已在修改前保存为 `scoped-cpu-seal-r2-source.py`，原hash04439cb1…；
当前seal SHA `03b744ed5ce698c518c9fa71f2fd10f43a995ae5a2066786f23cb22c5af26364`。

R3组件56PASS（53901／`3e012c`，8.63秒），主代理56PASS
（83633／`d246ae`，8.86秒），较R2增加11项；当前总计94＋42＋56＝192个不同组件测试。
限定R3审查 `independent-scoped-cpu-seal-r3-component-review.json` SHA
`ed1ba30bcab8e32a20cee14477604f2bda5e7ec92b5ca2473b28ca8f3aef54f3`。
它的历史R2引用不能作为当前递归源码tree通过证明：R2记录的seal源码/测试路径已变化。
整套当前审查必须直接绑定当前源码，不用历史组件PASS补齐未审范围。

新20源码/测试与三组回归、边界/Ruff/Mypy39/build/diff终态记录于
`scoped-cpu-entrypoint-components-r3-engineering.json`，SHA
`58bf9e3bfc7474d6172149f0f612a6348595e90d397e05f6bd87ad8e0713dfaa`。
旧R2记录完整保留为历史，不再声称其20个路径当前全部同hash。
全仓35677仍未终态，且不覆盖CPU新文件；尚不能生成当前CPU整套六项工程PASS或调用seal。

整套有限准备范围审查已完成：`independent-scoped-cpu-implementation-review.json`，SHA
`dd39695332e6f2ffc579e28b008a9dd888ba15d6131b0d2438310bb445585a6f`。
55显式entries形成124当前源码/测试/配置依赖，主代理重核全部hash一致（`b85c19`）。
只在六项真实同版工程全终态通过后支持未来初始化和完整准备；本审查时仍不能调用seal，
也不签具体prepared scope、实际冷回放、真实模型或后层准入。旧组件记录只作历史观察，不混入当前递归依赖。

## 当前全仓验证与下一执行边界

旧基线35677已exit0：3097 passed／1 optional Host SDK skip，3811.95秒，terminal `f04027`。
六项工程终态记录 `scoped-execution-wiring-engineering-terminal.json` SHA
`92f25d2f480ccc6a66819cb11979ea65713908f7268ec9ea4b047aad11fb97da`，明确不覆盖随后CPU代码。

当前完整回归67617使用独立持久basetemp：
`evidence/v0222-admission-offline/20260912-read-scope-r1/cpu-r3-pytest-RTL705/tmp`。
启动记录 `scoped-cpu-r3-full-regression-start.json` SHA
`de00a4cd1fcb6daf1884dd03d8063323a61b2c37de5bc06f74b063db653d03c3` 保留启动时观察；
其后实际收集3290（`f57415`），续查仍运行（`789941`，43%）。579启动源码pin与124独审依赖
在续查时全部一致（`1d0183`）；保持代码/测试冻结，不因观察间隔重启或重复启动。

CPU_ROOT及新live ROOT仍未创建。等待当前同版工程终态后才能初始化并准备完整16＋80参考；
实际40冷进程、父finish/gate及每准入初次/收口读取、hash、parse、bytes、墙钟/CPU计量仍须兑现。
现有组件耗时和synthetic PID集成不填补这些证据。既有vLLM HTTP是唯一真实模型接口，
本次未调用它，未操作GPU、驱动或服务；旧停止批和后层依赖不变。

### 逐准入计量缺口的独立复核

`/root/v222_review`只读复核后确认：这是冻结设计要求的观测缺口，不是追加业务门。
现有scope统计未被持久化；`json_parses`计失败尝试但不含历史JSONL解析，不能当作全部parse量。
原 `run_child`只记录墙钟/PID/退出，父进程CPU不包含子CPU。`_operation`生成器的yield不是结束，
完整操作计时必须涵盖收口后的期限检查与事务退出。

拟以CPU父/子bootstrap中guard之后的显式观测补齐，保留原Batch/reader/验收和完整矩阵；
只在内存累计，不在准入到发送间插入写盘，进程安全结束时另存实例外计量制品。
计量开销仍计入原期限，嵌套时间不相加；被杀worker缺失终态就记缺失，不补造成功收口。
外层time/cProfile不能自动覆盖子进程或这些粒度。具体观测器尚未实施/验证，不能据方案宣称已满足要求。
当前Python为3.11.13；源码冻结期间不改入口，先收口已有全仓回归再合并所需观测实现。

记录 `scoped-cpu-measurement-gap-review.json`（主代理记录独立审查意见，并非执行准入），SHA
`869d5e8cad0a4cfe0997bc4b2e8f8a24f834f5fa4d1366640967f1634facf988`。
七项所读源码/设计hash复核一致（`0e5e3f`）；67617续查`93b86b`仍在运行，未重新启动。
