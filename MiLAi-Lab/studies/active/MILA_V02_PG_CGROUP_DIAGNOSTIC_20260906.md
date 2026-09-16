# MILA-V02-05：PG容器资源观测与事务退出等待

状态：`TRANSACTION_EXIT_IO_PRESSURE_COINCIDENCE_OBSERVED / P1_P2_P4_PARTIAL`。
本轮600读取、150导入全部完成并满足本次客户端候选门。事务退出长尾与PG容器I/O压力
出现同窗证据，未观察到该容器自身CPU配额限流；不是逐请求磁盘根因证明，也不覆盖历史失败。
新增实验模型生成及Provider tokenize均0，Product源码未改。

## 为什么增加这项观测

上一轮基线最慢调用约320ms，事务退出约310ms，客户端GC交集仅0.30ms；缺少PG资源计数，
无法区分I/O等待和容器限流。本次只在Lab既有资源采样器中增加自有PG容器的cgroup读取。
通过Docker返回的完整容器ID、PID启动时间及cgroup成员路径绑定身份；身份变化或必要文件
不可读会停止，不回退读取其他容器。没有查询Product私有SQL、注入查询或改动PG限额。

采集`cpu.stat`、`cpu.max`及可用的CPU/I/O压力、I/O量、内存文件。可选文件缺失单列，
本机`cpu.stat.local`不可用，不当作0。CPU计数以微秒计；自身配额限流不能涵盖祖先限流，
因此不能把自身计数不增长扩大为“完全没有CPU调度等待”。语义参照
[Linux cgroup v2文档](https://docs.kernel.org/admin-guide/cgroup-v2.html#cpu-interface-files)。

配置中采样间隔为50ms，存储大小检查仍每500ms；实际采样起止都记录，不假定等间隔或原子
快照。对每条工具调用找完整包围它的前后样本，再作累计计数差；无包围或计数倒退保持未知。
窗口包括该容器的其他工作，窗口间可能重叠，不能当逐请求独占耗时，也不能把窗口增量相加。

## 冻结条件与执行

配置：`configs/v02-pg-cgroup-diagnostic.json`。
产物：`artifacts/v02-e2e-generality/p1-pg-cgroup-20260906a/`。
Product pin仍为`38b43df09b2bd872fe6112cb1787b5247cd28d2896ac70fb595c13002536f342`。

```bash
uv run python tools/run_v02_mixed_pair.py --config configs/v02-pg-cgroup-diagnostic.json --root artifacts/v02-e2e-generality/p1-pg-cgroup-20260906a
uv run python tools/summarize_v02_mixed_timing.py --root artifacts/v02-e2e-generality/p1-pg-cgroup-20260906a
```

沿用两臂各1000条State、三份512/2048/8192字节完整来源、同catalog及12次预热；
三轮各5秒、读取20/s，mixed导入10/s，客户端6读+2导入上限。API线程/池最大8，
PG 2 CPU/1 GiB，零重试，仍只读TASK/SESSION/PROJECT三个活动State。
两臂独立服务按baseline→mixed执行，相同观测配置；没有扩量、删除首尾字段或来源。

| 轮次 | baseline读取P95/P99 ms | mixed读取P95/P99 ms | P95比值 |
|---|---:|---:|---:|
| 1 | 13.012 / 31.135 | 15.216 / 17.297 | 1.1694 |
| 2 | 13.124 / 14.107 | 15.533 / 17.188 | 1.1835 |
| 3 | 12.630 / 15.569 | 15.688 / 19.631 | 1.2421 |

本次客户端P95≤50ms、逐轮比值≤1.5均满足；无拒绝、超时、错误、正文或版本不一致。
150个导入目标按既有轮末readiness及公开GET核对，未测精确逐写索引延迟。
SDK物理调用2313、MCP工具630、Runtime HTTP日志2955（含辅助请求），三层不相加。
历史57.15%退化失败、上轮基线99完成/1拒绝及本次通过分别保留，不宣称稳定服务SLO。

## 新证据与不能推出的结论

600/600读取完成Runtime/MCP关联，也全部有完整包围的PG容器采样窗口：

- baseline最长事务退出36.900ms，对应工具调用44.620ms。包围窗口前后余量约5.692/0.568ms；
  PG I/O full/some压力累计均增加36.653ms，自身CPU限流次数和时长增量均0。
- mixed最长事务退出23.510ms，对应工具调用33.231ms；包围窗口I/O full增加21.954ms、
  some增加23.154ms，自身CPU限流增量0。但窗口前后余量30.125/48.762ms，归属精度更弱。
- 两臂最大MCP handler外等待分别41.343/37.000ms；对应调用无客户端GC交集，包围窗口
  没有PG I/O压力或自身CPU限流增量。不能用PG I/O解释这另一类等待。

两臂分别421/440个容器样本，整个采样区间自身CPU限流累计不增长，`cpu.max`始终为
`200000 100000`。该区间还包含预置及轮末工作，不能把全程压力累计当作纯读取成本。
观测程序并非零开销：单次cgroup读取平均0.940/0.998ms、最大28.738/37.493ms，
实际最大采样间隔79.055/87.930ms。读取墙钟也含采样进程被调度等待；不将其当作纯采样CPU时间。

可得结论是“本次较长事务退出与容器I/O压力同窗，没有自身配额限流证据”。不能因此确定
具体fsync、WAL文件、块设备或哪条PG语句，也不能回填历史310ms调用的未采集资源信息。
没有旧/新实现配对或观测开销隔离，本轮通过不代表观测代码优化了服务。

## 检查与收尾

新身份/缺失/计数窗口控制8通过；最终Lab **288 passed（2.45s）**，Ruff、边界、mypy、
build通过。分析函数新增的两条长行经Ruff修正。运行前源码摘要在`plan.json`，采集类行为
未变；新增离线窗口分析函数及分析入口的最终摘要另记`final-observation.json`。
Product源码未改，不重复其全套回归并冒充新验证。

源码pin确认一致，两臂API/worker/MCP进程核实不存在，自有PG已停止并保留数据；共享服务
未触碰。无API/Schema/权限/Canonical/事务语义变化，无迁移或部署，Schema仍
`NO-GO FOR SCHEMA FREEZE`。

下一步优先补齐MCP handler前后边界，提交等待若需继续定位则复用公开或Product自身运行
诊断；没有证据前不扩池、关闭同步提交、取消访问审计或扩大负载。网关SLO、多租户公平性、
持续负载及端到端语义效果仍未验证，D4/D5未进入，Goal继续进行。
