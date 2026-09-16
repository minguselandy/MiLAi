# MILA-V02-05：客户端GC观测与基线停止

状态：`BASELINE_CLIENT_BOUNDARY_FAILED / MIXED_NOT_ENTERED`。
基线首轮100次计划读取中99次完成、1次被客户端在途上限拒绝；完成请求的计划发送至响应
P95为148.615ms，超过冻结50ms目标。遵守原停止条件，后续轮次及mixed臂没有运行，未重试、
扩大容量或另选一次通过结果。本轮新增模型生成和Provider tokenize均0。

## 验证的问题与实现范围

前两轮诊断都有约57ms的MCP handler外等待，但没有客户端暂停记录，无法判断它是否由
负载客户端的GC造成。因此只在Lab负载客户端增加默认关闭的`gc.callbacks`观测，
用同一进程的monotonic时钟记录start/stop/generation，最多8192项；溢出、未闭合或乱序
记录保留未知，不填成零。回调不改变GC开关、阈值或触发策略，异常退出仍移除回调并留存记录。

关联器将GC区间与实际工具调用区间取交集，结果单列。它不从延迟、P95或预算中扣除GC；
GC与服务处理可能重叠，不能把交集视为可直接相减的独占时间分量。观测只覆盖客户端的
GC回调区间，不覆盖服务端GC、编码、网络或调度，也不证明观测本身零成本。

Product源码未改变，继续使用pin
`38b43df09b2bd872fe6112cb1787b5247cd28d2896ac70fb595c13002536f342`。
没有新增Memory模块、API、数据库实体或权限规则。

## 冻结运行与结果

配置：`configs/v02-client-gc-diagnostic.json`。
产物：`artifacts/v02-e2e-generality/p1-client-gc-20260906a/`。

```bash
uv run python tools/run_v02_mixed_pair.py --config configs/v02-client-gc-diagnostic.json --root artifacts/v02-e2e-generality/p1-client-gc-20260906a
uv run python tools/summarize_v02_mixed_timing.py --root artifacts/v02-e2e-generality/p1-client-gc-20260906a
```

保持此前1000条State及三份完整来源、12次预热、每轮5秒20读取/s、客户端6读+2导入上限、
API线程/池最大8、PG 2 CPU/1 GiB和零重试。新观测在两臂同样配置，计划仍是三轮baseline
再三轮mixed；本次只有baseline第一轮实际进入，不构成有效的两臂比较。
没有删除任何正文首尾字段或来源。

| 观察 | 结果 | 可得结论 |
|---|---:|---|
| 首轮计划 / 实发 / 完成 / 客户端拒绝 | 100 / 99 / 99 / 1 | 拒绝未发送，不是Runtime的503或超时 |
| 完成请求计划至响应P95 / P99 | 148.615 / 320.401ms | 基线门失败；拒绝单独计数，不混入成功分布 |
| 逐请求Runtime/MCP关联 | 99 / 99 | 已发送的计量读取都可关联 |
| 最慢工具调用 / 事务退出 / 池获取 | 319.975 / 309.995 / 0.017ms | 主要长尾仍位于事务退出段 |
| 该调用的客户端GC交集 | 0.301ms | 本次长尾不能归因于客户端GC |
| 最大handler外等待 / 该调用GC交集 | 37.243 / 0ms | 本次另一段外部等待也未与客户端GC重叠 |

客户端GC捕获完整、无溢出，前后开关和阈值一致；99次读取中6次有交集，最大0.796ms。
客户端最长GC回调区间34.253ms发生在计量工具调用之外，不能拿全进程最大GC时长解释某条
请求。它也不能追认历史两条57ms等待的根因；那两轮没有此项观测。

被拒绝项为首轮index=82，实际已有6条读取在途，拒绝事件没有dispatch时间或Runtime回执。
本次没有测量导入流量，mixed不是失败或通过，而是`NOT_ENTERED`。
计量之外仍有预置保存和预热：SDK物理调用1005、MCP工具114、Runtime HTTP日志1125，
后者均200/201，包含辅助请求。三层调用数不可相加；初始化及开发检查另属工程成本。

保留的PG日志只显示初始化/关闭检查点，关闭时终止autovacuum属于清理；没有足够的逐请求
等待或资源限流记录，将309.995ms归为磁盘fsync、CPU限流或检查点均证据不足。
此前一轮客户端门满足与本轮失败均保留，不能只选通过轮次宣称服务稳定。

## 检查、收尾与下一步

局部GC/关联控制18通过；完整Lab **280 passed（2.42s）**，边界、Ruff、mypy、build通过。
Ruff发现一条新增长行，修正后通过。Product源码未改，未重复其整套回归或将旧结果计作新测试。
源码pin验证通过，真实负载的API/worker/MCP进程已核实不存在，自有PG停止并保留数据；
mixed服务目录未创建。没有触碰共享服务、部署或迁移，Schema仍为`NO-GO FOR SCHEMA FREEZE`。

客户端GC在本次不是所观测长尾的主要解释。后续应补齐MCP handler前后边界及PG提交等待的
观测，先核查可复用的公开或Product自身诊断能力；不通过关闭GC、取消访问审计、降低持久化
保证或提高并发上限来制造达标结果。P1/P2/P4仍PARTIAL，D4/D5未进入，Goal继续进行。
