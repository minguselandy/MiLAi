# MILA-V02-05：窗口焦点复用与范围读取确认

状态：`LOCAL_COMPILER_EQUIVALENCE_CONFIRMED / C1_BOUNDARY_MET / C8_BOUNDARY_MISSED`。
已修复窗口预算二分中对同一正文的重复焦点扫描。局部编译明显提速且完整输出不变；真实
MCP读取并发1三轮达到客户端300ms门槛，并发8首轮P95为1867.128ms，整体服务门仍未通过。

## 窄改动与局部证据

在Product自身开发环境，用50个512/2048/8192字节Evidence窗口及8192 token编译预算做
无数据库局部剖析，原`_fit_window`为43个窗口尝试475个截取长度，每次都调用相同正文的
`_focused_excerpt`扫描。扫描位置与候选长度无关，却在二分循环中重复计算。

`runtime/src/milai/application/memory_context.py`将焦点计算与按位置截取拆开：单窗口及
必要窗口联合适配在循环外计算焦点，循环内复用局部整数；独立截取入口保留原规则。
没有跨请求缓存、不保留来源正文、不改变权限、来源集合、预算、排序、截取位置或事务。
连原casefold位置约定也保持，Unicode定位语义未在此次优化中另作修改。

Product的Git外`runtime/var/v02-excerpt-focus/`保存冻结输入、修改前完整MemoryContext、
前后源码hash、profile及计时。每版10次无profile编译的中位数为140.307→48.137ms；
当前完整MemoryContext逐字段等于修改前结果（正文、窗口、选择、预算与trace均包括）。
一次profile的正则search调用478→46。此为Product内部局部诊断，不是Lab黑盒效果或服务SLO，
也不是一个“所有任务均加速”的结论。

新增8个回归控制覆盖不同位置、数字、无匹配、空查询、长正文、Unicode、单/联合窗口，
核对旧截取规则、输入不变、引用保留、预算上限以及每窗口只扫描一次。

## 公开MCP确认

新锁：`data/locks/v02-excerpt-focus-product.lock.json`。
源码pin：`09237fd4edcbf3642435703db709dcb329382186273c70db6ceeadab82d052b9`。
锁digest：`b027e1ecc3b4faff47a2b53582587786b94e23d8ddd3cb217d9d5de0942a7547`。
当前E2E/SIM02候选配置跟随新锁；已执行的旧配置与失败记录不改。

```bash
uv run python tools/check_v02_e2e_live.py --service-calibration --config configs/v02-scoped-recall-excerpt-focus.json --root artifacts/v02-e2e-generality/p1-scoped-recall-20260906c
```

沿用b的1000份完整来源、两个项目、三个正文长度、预置并发4、API/池最大8、PG 2 CPU/
1 GiB、2核affinity、就绪批次、MCP绑定、上下文预算及300ms阈值。两次全部1000个来源请求
hash相同；首次公开响应仅规范化重新产生的Evidence ID和context_id后完全相等。
没有降低正文长度、移除首尾、放宽预算或跳过范围控制。

正常范围召回、外项目标记MISS、伪造scope参数拒绝继续成立。预算受限视图继续单列：
共99次MCP调用，97个预算受限视图、1个MISS、1个预期拒绝。

| 实际轮次 | 读取数 | 客户端P50 / P95 / P99 ms | 完成/s |
|---|---:|---|---:|
| 并发1，第1轮 | 24 | 263.231 / 298.531 / 300.009 | 3.696 |
| 并发1，第2轮 | 24 | 262.266 / 288.069 / 318.386 | 3.732 |
| 并发1，第3轮 | 24 | 257.797 / 296.802 / 311.011 | 3.746 |
| 并发8，第1轮 | 24 | 1818.841 / 1867.128 / 1872.405 | 4.323 |

按冻结门停止并发8后两轮，未继续扩量或重跑。P99单列，验收仍按预先冻结P95，不事后
新增或撤销门槛。b只取得一轮单并发，因此不能用本轮三轮结果作严格完整配对收益估计。
局部140→48ms也不能套用为真实服务的同比降幅。

SDK1021次物理调用；Runtime1124次HTTP（1000个201、124个200）；MCP99次，层次不相加。
Runtime98次resolve的application P50/P95为215.067/250.450ms，连接外剩余区间P50/P95为
168.868/209.552ms；池获取之和最大0.205ms。没有Runtime请求ID的MCP呈现继续只作分布报告，
不强配请求或用两个P95相减归因。

源码确认范围resolve仍调用共享同步SDK，`MilaiClient._run`持有`RLock`运行完整协程；
Working State已有的异步接入没有覆盖此路径。并发8延迟上升且吞吐只小幅增长，支持优先
核查这处串行边界，但未隔离出锁在本轮每个请求中的等待时长。

## 检查、清理及剩余工作

相邻37通过；Runtime真实PG完整回归1005通过、1项因SDK未加入测试导入路径而跳过。
补齐`python-client/src`与`openworker-mcp/src`后，仅补跑该集成项，1通过（2.99s），原跳过日志
保留。Runtime Ruff/mypy（189文件）/build通过。Lab完整309通过（2.46s），边界/Ruff/mypy/
build通过。无其它adapter代码改动，不把未重跑的旧检查计入本轮。

PG回归记录位于`artifacts/v02-e2e-generality/p1-excerpt-regression-20260906a/`，属于Product
自身回归，不是Lab黑盒实验。补跑发生在性能运行停止后，未让两者同时占用测试资源。
本轮两个自有PG已停止，API/worker/MCP均已核实不存在，数据保留，共享服务未改。
没有模型生成或Provider tokenize，无API/Schema/权限/Canonical/迁移变化；
Schema仍`NO-GO FOR SCHEMA FREEZE`。

下一增量针对现有范围resolve的同步调用锁，复用已建立的异步生命周期并保持逐请求主体、
工具schema、异常/取消、预算及输出语义；先做重叠和身份控制，再同条件确认。不能通过增加
池、缩小返回或降低并发替代修复。D4/D5未进入，整体Goal仍未完成。
