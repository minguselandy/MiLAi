# 并发读取、撤权与冷恢复组合验证

状态：`CONCURRENT_FAULT_COMPOSITION_VERIFIED_NOT_FULL_D3`。0模型调用，Schema仍
`NO-GO FOR SCHEMA FREEZE`。原模型任务失败不因本项工程通过而改变。

配置`configs/v02-concurrent-faults.json`，工具`tools/check_v02_concurrent_faults.py`，
产物`artifacts/v02-e2e-generality/concurrent-faults-20260907a/`。当前Product pin
`cdccd06328cd07eb77c2fc3956c3df742c30b2c38ae5aa7ee65a7d3c31c30c5c`复核通过。

独占API/PG/两MCP，2个逻辑CPU、PG 2 CPU/1 GiB、API线程8/连接池8/等待32。
使用合成来源，先SIGKILL worker，再由公开MCP保存两个不同项目的State。两个reader各16次
读取期间，同一State/expected_version/不同operation ID的两次更新同步起跑，并撤销另一
项目的来源。额外各4次撤权后读取；随后SIGKILL API，再启动新API/worker/MCP读取与重放。
未直接写数据库，不删除引用/首尾字段，不调用模型。

实测51条公开操作观察、20.293195秒；另有2次公开Evidence capture。

| 检查 | 直接结果 |
|---|---|
| CAS竞争 | 一次v2成功，一次明确STALE_WORKING_STATE；不同operation ID |
| 请求重叠 | 13对读取/修改的客户端请求区间重叠；不等同于数据库内部并行度 |
| 撤权后披露 | A的16个在撤销回执之后发起的读均隐藏正文；旧幂等回执也隐藏 |
| 正常同伴 | B的15个撤权确认后读取持续保持首尾canary和允许版本，无A正文 |
| API不可用 | 两个MCP均返回错误，不返回缓存State正文 |
| 冷恢复 | 新MCP下A仍隐藏；B保留CAS赢家的版本和完整内容，赢家操作可幂等重放 |
| 清理 | API/worker均不存在，PG已停止、无OOM；共享服务未改 |

回执前启动、回执后结束的读取没有被错误算作撤权后开始的请求。结果分别记录请求
start/end和撤销回执时点，避免将合法的并发快照误判为泄漏。

新增5个检查器回归覆盖串用、泄漏、缺少足够post-ack观察及正常同伴内容丢失；全Lab389
通过（3.31秒），boundary/Ruff/mypy/build通过。原单字符测试canary会与JSON键撞词，已
修正为唯一合成标记；首次检查器失败不是产品失败。

本项补充D1/D3的组合故障证据，仍不证明多租户公平性、高负载SLO、掉电耐久性、API请求
在途被杀后的结果、模型效果或整个D3通过。原有来源隔离、投影旧任务与性能证据继续分项。
