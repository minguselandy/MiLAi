# MILA-V02-05：完整请求剖析与日期扫描复用

状态：`LOCAL_EQUIVALENCE_CONFIRMED / PUBLIC_RUN_STOPPED_AT_PROJECTION_READINESS`。
完整Runtime请求定位到Evidence解释中的重复日期扫描。本轮只复用同一span已取得的首个日期
匹配，不改变日期规则、优先级、来源或预算；局部结果等价。公开运行在投影就绪超时后停止，
没有进入范围控制或延迟测量，服务性能改善尚未确认。

## 定位与局部比较

Product自己的开发脚本通过Flask test client进入真实`/v1/memory/resolve`路由，使用原reader
认证和Host binding，连接上一轮d保留的自有PG及1000条完整来源。原API/worker/MCP未重启。
这不是Lab黑盒、网络延迟或网关SLO测量；调用正常读取/审计路径，不直接修改业务表。

修改前后分别2次请求：一次预热、一次cProfile。固定查询、项目scope、50结果/120候选、
8192上下文token和2000ms Runtime预算。前后完整请求剖析约264.707/224.277ms，仅各一次，
带分析器开销，不作服务同比收益结论。修改前Evidence解释约93ms，日期range扫描约35ms，
事件时间解析约34ms；两处对同一文本运行相同日期模式。

原始Product开发记录分别位于`runtime/var/v02-full-resolve/`和`runtime/var/v02-date-scan/`。
前者保留修改前源文件与profile，后者在预热时对真实240个span运行修改前后解释并逐项比较，
随后恢复原函数执行干净profile。完整解释候选及suppressed计数相等；新旧请求的完整
Memory Context（含文本、窗口、来源、预算及compile trace）相等，无ID或字段删改。

对捕获的相同240个span，交替先后顺序执行各10次非profile局部计算，所有完整结果相等；
解释阶段中位87.761→55.046ms。整个profile中regex search次数3796→1876，减少1920次，
对应240个span各8个日期模式的重复search。该局部测量不能替代真实MCP请求确认。

## 改动及边界

`runtime/src/milai/application/evidence_semantics.py`在收集全部日期range时附带记录每个模式
的首个match，交给同一span的事件时间解析复用。独立formation时间解析仍使用原直接search。
模式选择顺序、首个无效日期的原有拒绝行为、相对时间的source anchor、日期数字排除、
候选ID和来源provenance保持原样。缓存只活在当前span处理内，不跨来源、请求或权限域。

没有新增Memory实体、模型、Reader、Hint或索引；没有删首尾、按测例路由、跳过解释/权限
检查、提高预算、修改日期regex或改变公共API。Schema/权限/Canonical/事务不变，无迁移，
Schema保持`NO-GO FOR SCHEMA FREEZE`。

新增13项检查覆盖多日期优先级、ISO/月份/数字日期、相对日/周末/星期/月、until、首个无效
日期、无日期、数量排除及相同文本不同来源时间；连同原语义/formation检查34通过（0.66s）。
首次新增夹具缺少source_ref/subject等来源元数据而得到零span，13失败保留为夹具错误；
补齐合法来源元数据后通过，未放宽生产来源校验。

Runtime Ruff、mypy（189文件）、build通过；Lab309通过（2.63s），边界/Ruff/mypy/build通过。
Runtime完整真实PG回归1019通过、无跳过（100.38s）；记录在
`artifacts/v02-e2e-generality/p1-date-scan-regression-20260906a/`。本轮准备新的自有数据库，
API/worker停止后执行Product自己的回归；预先设置SDK源码路径，使可选集成项正常执行。
MCP/SDK源码未改，未重复或追认上轮测试。

## 固定运行身份

新锁`data/locks/v02-date-scan-product.lock.json`，源码pin
`f7382a1bbd35c5fd168645779d2d2b409c179c54aec3478225bdfed3f0d4c3bf`，锁digest
`a00bcc4ecf81edadbd44bde37e95b087ce4608e491ce8b2bebe67a0b125dd0bf`。
当前E2E与已关闭的SIM02候选只同步pin，不增加模型授权；旧锁、旧配置和失败结果保留。

公开确认配置`configs/v02-scoped-recall-date-scan.json`继续使用1000来源、两项目各500、
512/2048/8192字节原正文、相同scope和预算、PG 2 CPU/1 GiB、2核affinity、API/池8、
预置并发4、读取档位1/8及300ms停止线。没有通过局部提速放宽门槛或扩负载。

```bash
uv run python tools/check_v02_e2e_live.py --service-calibration --config configs/v02-scoped-recall-date-scan.json --root artifacts/v02-e2e-generality/p1-scoped-recall-20260906e
```

1000个来源均取得保存回执，输入请求hash与d全部相同；投影就绪前11批通过，第12批
（begin=550）在5002.133ms后返回`PROJECTION_READINESS_TIMEOUT`/HTTP408，当前水位585、
目标602、版本一致、无dead-letter gap，`projection_work_started=false`。保存成功和索引
就绪分开记录；没有因为来源已保存就进入读取，也没有追加等待、重试、扩样或改5秒门槛。

本轮SDK物理请求1013（1000保存、12就绪、1能力），MCP工具调用0；Runtime HTTP1018
（201×1000、200×17、408×1），含服务辅助请求；不同层不相加。范围控制和延迟均未进入，
不能拿上一轮的scope结果充当本轮通过，也没有新P95或完整catalog/首个MCP结果可比较。

worker在15:50:44.072 UTC仍报告正常cycle及585个Evidence投影；就绪请求在15:50:45.062
UTC超时。日志随后出现的`AdminShutdown`位于清理停止数据库时，前置pool warning时间为
15:50:45.987 UTC。不能把这个清理错误写成最初就绪失败原因。保留cycle已有的lease、
skip、投影与水位计时，当前只确认水位未在冻结期限内达到目标，尚未锁定耗时根因。

## 收尾与下一步

公开运行的API/worker/MCP已核实不存在；本轮回归PG、性能PG及剖析复用PG均经docker
inspect确认停止，数据保留，共享服务未动。下一步先分析保留的worker阶段计时及投影
水位推进路径，明确为什么本轮在5秒就绪边界停下；不通过反复重跑等待一个通过结果。
日期复用可保留为等价的局部优化，但服务性能收益需后续独立确认。

新增模型生成、Provider tokenize及模型分配均0。完整P1/P2/P4和D4/D5尚未完成，
本轮不产生模型记忆效果或泛化结论。
