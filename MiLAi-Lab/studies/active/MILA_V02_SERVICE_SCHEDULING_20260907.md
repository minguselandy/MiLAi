# 当前服务确认、调度观测与私人用户异步隔离

状态：`SERVICE_GATE_FAILED / PRIVATE_ASYNC_BINDING_MECHANISM_VERIFIED`。
完整D3仍未完成，正式D4/D5未进入。两条新非模型运行各自封存，未自动重跑或覆盖失败。

## 当前版本固定负载确认

配置`configs/v02-mixed-confirmation-20260907.json`沿用既有1000 State、三份完整来源
512/2048/8192字节、3轮×5秒、20读/秒、mixed附加10导入/秒、6读/2导入在途、
API线程/池8、两个CPU affinity、PG2CPU/1GiB、零重试、L1读取P95≤50ms及1.5倍退化边界。
这项L1负载与用户接受的约525ms范围检索分开，不重新优化旧300ms范围检索目标。
Product pin `97eaac6de36a96e903af0b41412a44e8c7715539ca12359b7be41f790a5754bc`。
此次是在保存/冷恢复和私人身份检查后，一次预先冻结的当前版本确认，不是算法改善比较。

```bash
PYTHONPATH=tools:src .venv/bin/python tools/run_v02_mixed_pair.py --config configs/v02-mixed-confirmation-20260907.json --root artifacts/v02-e2e-generality/mixed-confirmation-20260907a
```

baseline第1轮100/100完成，计划发送至完成P95/P99为12.180/13.136ms；第2轮87/100完成，
13次`CLIENT_CAPACITY_REJECTED`未发送，完成子集P95/P99为5608.522/5808.029ms。
第三轮及mixed没有进入，不能将未发送请求当作服务端503，也不能计算未运行配对的退化比。
187个实际读取的完整payload/版本均核对正确，所有187个公开request指纹均可关联计时。

最长实际工具调用3942.162ms，其中MCP入口前2599.698ms，handler1298.496ms，
Runtime application930.819ms，数据库获取0.022ms、持有653.137ms、事务退出74.459ms。
负载器最长计划至实际调度延迟3738.730ms，资源采样最大间隔2.518秒。
这些证据显示多处等待，不能归因于尚未运行的导入、单一数据库提交、GC或确定的主机故障。
运行后全机进程CPU快照不能回填此前时窗的CPU原因。

## 增补可选调度观测与独立诊断

Lab既有`v02_cgroup_observation.py`增加`host_scheduler_sample`，服务采样器按可选
`observe_host_scheduler`调用，默认关闭。采集主机`/proc/stat`、CPU/I/O pressure，以及
本次拥有的API、worker、MCP、负载器主线程`schedstat`。记录PID/start ticks以识别身份变化；
进程退出或不可读时明确UNAVAILABLE，不填零，不读取凭据或任意进程正文。
主线程计数不等于全进程所有线程，主机计数包含其他服务，不作请求独占因果归属。

针对上述真实观测缺口，仅执行一次独立baseline诊断，原负载/资源/停止条件保持；
同时启用已有PG cgroup、client/MCP GC观测，GC策略不变。

```bash
PYTHONPATH=tools:src .venv/bin/python tools/check_v02_e2e_live.py --service-calibration --config configs/v02-host-scheduling-diagnostic.json --root artifacts/v02-e2e-generality/host-scheduling-diagnostic-20260907a
```

第1轮100/100完成，P95/P99为18.272/115.590ms；第2轮99/100完成，1次客户端未发送，
P95/P99为141.688/313.155ms。第三轮未进入，诊断仍未过服务门。5秒级停顿没有复现，
不得据此宣布修复或将两次运行拼为稳定基线。

199读取全部指纹匹配，32份调度/PG采样完整记录。最慢调用312.767ms，handler302.461ms，
Runtime client302.311ms，而application4.009ms、数据库持有3.599ms，获取0.021ms。
同一包围时窗1.264秒内，PG CPU限流增量0、I/O full pressure约6.527ms；该调用client/MCP
GC重叠分别约0.307/0.496ms。主线程运行队列等待API/MCP/client分别1.589/2.247/10.960ms，
这些包围窗口计数不等于该请求的独占时间。第二慢285ms主要位于MCP入口前约259ms。
另一个164ms调用包含约94ms事务退出等待，不能将所有长尾合并成同一个原因。

当前可定位到的下一缺口是应用处理之外的HTTP/入口等待；不能由残差直接认定具体网络、
线程池或事件循环故障。没有扩大连接池、关闭同步提交、去掉鉴权或删减正文。

## 私人用户与公平范围

线上`authenticated_private`模式由可信issuer/sub派生私人project/principal，但Runtime
仍按部署配置绑定tenant。ADR-047的每tenant数据库上限不能直接当每个登录用户的公平份额。
现有签名用户并发测试走同步测试客户端；本次增加线上默认的async State工厂路径检查：
两个不同签名用户在同一MCP中，热点用户读取被阻塞时，普通用户在释放热点前已完成；
热点返回200或503后，普通用户均继续正常。三次实际模拟Runtime请求、两种可信principal，
伪造project/tenant不改变绑定，无同步fallback或隐式重试。

测试复用Product的`test_aigcit_http.edge`及`AsyncMilaiClient`，下游Runtime响应为受控传输。
这证明认证与异步装配下的独立推进/身份隔离，**不是**真实PG负载、多租户网络网关、
任意用户数量公平或生产SLO。未因此增加队列、调度器、数据库实体或用户准入限制。
首次测试错误地要求只读失败返回写入UNKNOWN提示，已纠正为检查只读错误、无正文和同伴正常；
不改变Product错误语义。Ruff行长已修正。

## 检查与收尾

Product MCP定向37通过；完整265通过、4跳过（原真实PG3项及计时校准1项默认跳过），
Ruff、mypy14源文件和build通过。本轮仅Product测试变更，未改Product实现，未将旧真实PG
通过数冒充本轮重跑；Lab实际负载两次均使用独占真实PG。
Lab观测器定向10通过，全量447通过（4.26秒）；boundary、Ruff、mypy30与build通过。
PID变化和缺失计数负控通过；采样器实际进入两轮运行且生成32个样本，非仅函数单测。

两条运行的API/worker/MCP/client均退出，PG exit0、无OOM，保留卷/配置/失败与原始请求。
共享服务未改，无迁移、线上发布或Canonical变更，Schema仍NO-GO FOR SCHEMA FREEZE。
新模型/tokenize/付费调用0；SIM01–12累计69请求1,304,756 raw保持。

证据入口：第一运行根`pair-result.json`、`transaction-timing-analysis.json`与baseline
`timing-correlated.json`、资源/请求/清理；第二运行根`mixed-result.json`、
`resource-samples.json`、`timing-correlated.json`、`terminal-audit.json`。
第二项审计入口为同级`audit-host-scheduling-20260907.py`。
本轮补充可归因观察和私人async路径证据，完整混合负载、负载下公平及正式模型泛化要求保留。
