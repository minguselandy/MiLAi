# MILA-V02-05：服务端GC与事务退出两类长尾

状态：`SERVER_GEN2_GC_PRE_HANDLER_OVERLAP_CONFIRMED / BASELINE_STOPPED`。
本轮基线300次计划读取中299完成、1客户端容量拒绝；第三轮P95失守，mixed未进入。
首次取得服务端第二代GC与handler前等待重叠的直接区间证据，另一次更长等待仍在PG事务退出。
新增模型生成和Provider tokenize均0，Product源码未改。

## 源码核查与观测方法

核对安装的MCP 2.0.0、httpx2 2.10.0及MiLAi适配层：带参数的现代`tools/call`会先通过
当前调用者的`tools/list`取得schema，用于Mcp-Param头校验；此路径发生在工具handler前。
工具参数模型在注册时创建并复用，静态Bearer验证采用常量时间比较，没有发现每次新建
参数模型或调用外部鉴权服务的证据。文件身份及有限结论记录在`source-audit.json`。
这没有证明GC对象来自tools/list，也不支持跨调用者缓存整个可见catalog。

Lab复用既有有界`gc.callbacks`观测器，通过相同解释器执行发布的`milai-mcp`控制台入口。
没有导入或替换Product私有函数、改写协议处理、修改GC开关/阈值，或绕过真实公开Memory API。
记录仅为时间戳和generation，最多8192项；缺失/溢出或时钟未验证时不计算重叠。
观测包装与额外对象分配可能影响时序，不能把本条件的暂停时长回填历史轮次。

为保留退出记录，包装器在Uvicorn恢复并重发SIGTERM后以SystemExit 143结束，使finally
可以写盘；Uvicorn自身清理仍先发生。这是诊断启动方式，不是产品CLI的新默认退出策略。
参数、异常退出、SIGTERM、回调移除及GC策略恢复由局部控制覆盖，真实服务退出也取得文件。

## 冻结运行与实际结果

配置：`configs/v02-mcp-server-gc.json`。
产物：`artifacts/v02-e2e-generality/p1-mcp-server-gc-20260906a/`。
Product pin保持`13999df2432148b9ec9cd2580164f3cae70ee2875b70a2a8dff316f5a0b3ce46`。

```bash
uv run python tools/run_v02_mixed_pair.py --config configs/v02-mcp-server-gc.json --root artifacts/v02-e2e-generality/p1-mcp-server-gc-20260906a
uv run python tools/summarize_v02_mixed_timing.py --root artifacts/v02-e2e-generality/p1-mcp-server-gc-20260906a
```

继续1000条State、三份完整来源、12次预热、三轮各5秒20读取/s，客户端6读+2导入上限，
API线程/池最大8，PG 2 CPU/1 GiB，零重试；未删首尾或来源。实际读取仍为三个活动scope，
未扩成范围检索。基线三轮完成100/100/99，完成请求计划至响应P95为14.685/12.425/218.272ms。
第三轮index=53已有6条在途，被客户端拒绝，未发送至Runtime；按冻结条件停止，未重跑。

299/299实际读取均关联且通过共享时钟验证。服务端GC记录完整、无溢出，前后策略均为
enabled=true、thresholds=[700,10,10]。

| 调用 | 客户端调用 ms | 关键区间 | GC / PG观测 |
|---|---:|---|---|
| 最大handler前等待 | 42.564 | handler前33.038ms，内7.625ms，后1.902ms | 第二代服务端GC 30.880ms完全位于handler前；客户端GC交集0 |
| 最慢调用 | 348.975 | 事务退出330.342ms，池获取0.025ms | 服务端GC交集0.839ms；PG包围窗口I/O full压力增量344.114ms，自身CPU限流增量0 |

因此不能用一个原因概括两类长尾。第一条在此探针条件下与服务端GC直接重叠，尚未定位
引发回收的具体分配热点；第二条的PG窗口前后还有约18.606/53.200ms余量，不能称其
344.114ms全部属于该请求，更不能确定具体fsync/WAL语句。

本轮没有计量导入，mixed未创建，不构成两臂效果比较。预置/预热另有正常写入：SDK物理
调用1005、MCP工具314、Runtime HTTP日志1325（含辅助调用，均200/201），三层不相加。
历史成功与失败原样保留，不把本轮归因为产品优化或端到端记忆效果。

## 检查、收尾及后续范围

局部CLI/GC控制10通过；完整Lab **295 passed（2.63s）**，边界/Ruff/mypy/build通过。
新测试的一条长行修正后Ruff通过；Product源码未改，未重复或追认其旧回归为新检查。
源码pin匹配，自有API/worker/MCP进程已核实不存在，PG停止且数据保留；共享服务未触碰。
无API/Schema/权限/Canonical/事务语义变更，无迁移/部署，Schema仍`NO-GO FOR SCHEMA FREEZE`。

下一步先核查服务端是否存在可以安全复用的重复对象构造；若没有明确收益证据，不增加
catalog缓存或改变GC策略。PG I/O等待与持久化保证独立处理，保留已测限制并补齐其余工程门。
完整服务验收、公平性、持续负载及语义效果仍未通过，D4/D5未进入，Goal继续进行。
