# MILA-V02-05：公开读取复测与计时边界

2026-09-07（Asia/Shanghai）执行，沿用20260906文件标识。Product pin保持
`10f713352d53d245fa3ad27e6a283b3a09410031fe7149c7e2ee18ed8afbbe86`。
本轮只修改Lab观测代码，没有Product源码、公开API、schema、权限或Canonical变更。

## 观测定义

静态核对确认客户端在全部轮次中复用同一MCP会话；初始化和工具目录获取在计时外。
MCP服务也通过lifespan复用AsyncMilaiClient及HTTP连接池，无需增加连接复用机制。

原`elapsed_ms`从调用前计至返回后完成完整响应序列化、范围检查和摘要计算。
本轮保留该边界、三轮计划和300ms停止门槛，仅增加收到响应的时间戳，将每个调用
拆为`call_to_response_ms`与`post_response_checks_ms`。取消或返回前失败时两者为null，
原异常继续传播；范围检查与全字段摘要未删减。配置修正了原来不准确的计时名称，
没有将新指标替换为验收指标。响应指标包含客户端协议处理，也不是Gateway SLO。

## 真实公开复测

原始证据：`artifacts/v02-e2e-generality/p1-scoped-recall-20260906i/`。
配置：`configs/v02-scoped-recall-context-work.json`。
来源1000条、两个项目各500条，512/2048/8192长度和首尾保留；1000条公开capture
请求body摘要与h相同（按集合核对，以免并发到达顺序影响比较），工具目录相同。
readiness请求包含新生成的Evidence身份，其body摘要不同，不作为来源内容差异。
CPU affinity仍为0/1（同核SMT），PG 2CPU/1GiB，池8，最大并发8；无扩大负载或重试。

| 轮次（每轮24请求） | 原整体P95 ms | 收到响应P95 ms | 返回后检查P95 ms |
| --- | ---: | ---: | ---: |
| c1-r0 | 154.851 | 118.696 | 37.605 |
| c1-r1 | 157.649 | 121.478 | 37.914 |
| c1-r2 | 146.607 | 110.307 | 38.964 |
| c8-r0 | 815.119 | 776.309 | 79.319 |

c8首轮超300ms，按原规则停止，其余两轮没有执行。三个分布各自取分位数，不能相加
或相减来推导分层延迟。检查代码是同步工作，也可能影响同一事件循环其他调用；这次
拆分本身不证明删除这些工作后的性能。历史h整体P95 1306.270ms保留为历史结果，
两次Product pin不同，不能把变化单独归因于Context优化或某个传输组件。

20批readiness及3个项目范围控制通过。99个MCP调用包含97个明确预算受限的DEGRADED、
1个MISS和1个预期拒绝；不得将DEGRADED记成HIT或完整任务答案。SDK物理调用1021；
Runtime日志1125条：1000×201、125×200，其中resolve98、readiness20、capabilities6、
ready1。三个层级计数不能相加。没有模型生成、Provider tokenize或实验额度增加。
本轮只验证固定项目范围，不声称租户公平性、完整语义正确性或端到端泛化。

## 验证与后续

新增4个观测边界控制覆盖成功、范围泄漏、取消、预期拒绝。执行结果：

- `uv run milai-lab-check-boundary`：通过。
- `uv run pytest`：328通过，2.66s。
- `uv run ruff check src tests tools`、`uv run mypy src/milai_lab`：通过（30源码文件）。
- `uv build`：sdist与wheel成功。
- 当前Product pin复核通过；无Product代码变化，复用上一轮最终pin真实PG1104通过证据。

独占API190619、worker190620、MCP190740均已不存在，独占PG确认停止，数据保留。
共享vLLM与公开MCP未修改。完整P1/P2/P4与正式D4/D5仍未通过，Schema仍为
`NO-GO FOR SCHEMA FREEZE`。下一步以当前版本的剩余完整请求工作量定位并发成本，
保持现有300ms门槛；不通过移除实验检查、权限读取或完整来源来宣布服务达标。
