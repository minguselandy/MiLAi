# HTTP阶段观测与当前混合负载

本轮补齐默认SDK可选HTTP阶段计时，真实请求关联有效；完整服务门仍未通过。
独立读取诊断完成300次；随后独立冻结的完整配对在混合第一轮发生1次客户端导入容量拒绝，
按原条件停止。不能把前一诊断拼成配对，也不能把旧长尾未复现解释为已修复。

## 实现与边界

`HttpxAsyncTransport(timing_enabled=False)`默认关闭；MCP CLI复用
`MILAI_REQUEST_TIMING_ENABLED`为异步State/resolve客户端启用。记录连接、TLS、HTTP发送、
响应头/正文接收与关闭阶段的单调时点；每请求最多32个事件，超量计数，未知事件不记录。
日志只含阶段名、时间、HTTP状态和公开request ID摘要，不含URL、正文、凭据或trace info。
成功、状态错误、超时、取消保持原行为，不增加重试、连接池容量或业务权限。

Runtime application计时从Flask开始处理起算，不含Waitress入口排队；HTTP响应头等待则
可能包含排队、应用、网络和调度。二者为嵌套区间，不能相加或把差值直接归为纯网络。
缺失/未匹配为未知。详见Product `docs/contracts/MILA_REQUEST_TIMING_V1.md`。
没有schema、canonical、权限、事务或migration改动；新计时代码未部署到公网私人服务。

当前运行Product pin：`84ccec2a5ffeb7813667c378a59df593e13c4cc47b5cba815f75ff3ac1931dc4`，
锁文件`data/locks/v02-http-transport-timing-product.lock.json`，两次执行前均验证。
历史pin及失败证据保持原归属。

## 真实执行

共同条件：1000条State、3份完整512/2048/8192字节来源、20次读取/秒、3轮各5秒、
读容量6/导入容量2、8个API线程与池连接、2 CPU affinity、PG 2 CPU/1 GiB。
固定L1 P95≤50ms、混合退化比≤1.5、无隐式重试。用户接受的525ms scoped recall独立保留。
GC仅观测，未改策略。

| 运行 | 完成与延迟 | 结论 |
|---|---|---|
| `http-transport-diagnostic-20260907a` | 300/300读；三轮P95 13.619/12.825/13.655ms | 独立baseline诊断，不是配对效果 |
| `http-timed-mixed-pair-20260907a` baseline | 300/300读；P95 47.659/14.639/12.478ms | 本臂完成 |
| 同一配对mixed第一轮 | 100/100读，P95 15.962ms；49/50导入，已完成导入P95 33.763ms | 1次CLIENT_CAPACITY_REJECTED，后两轮未进入 |

完整配对计划600读/150导入；实际400读/49导入，进入轮导入分母50；完整配对比值未取得。
两臂原始来源请求摘要、归一化State、catalog相同，读回完整payload和版本由固定runner断言；
实际读取正文未逐条wire dump，不能将响应摘要称为完整原文转储。
49个已提交导入均通过公开READY屏障，轮末观察只能提供就绪时间上界，不能当精确索引耗时。

拒绝的import 28没有dispatch，不是Runtime 503。当时import 26/27仍在途：

| import | 保存调用ms | application ms | blob file fsync ms | DB acquire ms |
|---|---:|---:|---:|---:|
| 26 | 220.859 | 217.808 | 205.527 | 0.016 |
| 27 | 120.230 | 117.026 | 106.317 | 0.017 |

公开回执request ID与Runtime计时唯一关联，两次调用覆盖原定到达时点。这次容量拒绝与
仍未完成的文件同步调用相符，扩数据库池没有相应证据。fsync区间包含调度，不能宣称纯设备
耗时；不取消持久化同步，也不据此解释旧313ms或5.6秒读取长尾。

## 核对与下一步

SDK：`uv run pytest -q` 188通过（新增9个计时边界测试），Ruff/mypy（14文件）/build通过。
MCP：同命令265通过、4跳过，Ruff/mypy（14文件）/build通过；跳过3个PG集成和1个计时校准，
本轮真实Lab负载另使用真实PG，不将它替代全部跳过用例。
Lab：`uv run milai-lab-check-boundary`、`uv run pytest -q`（447通过，4.38秒）、
`uv run ruff check src tests tools`、`uv run mypy src/milai_lab`（30文件）、`uv build`均通过。

两份终态审计脚本位于`artifacts/v02-e2e-generality/audit-http-transport-20260907.py`和
`audit-http-timed-pair-20260907.py`，均已执行。诊断300条、配对400条读取与HTTP/MCP/Runtime
唯一关联；独占API/worker/MCP/load client已退出，PG exit 0、无OOM、卷保留，共享服务未动。
新增模型/tokenize/付费均0，总账仍69请求、1,304,756 raw，pending 0。

线上另只读核对：`milai-aigcit.service` active，策略v2 `authenticated_private`。
合法登录用户自动按可信issuer/sub绑定私人记忆，无逐人白名单；此事实不等于负载公平已验证。

下一步检查现有零等待客户端容量合同与实际批量导入需求：若引入有界等待，应作为预先声明
的新负载条件，保留原定到达时间计入延迟并保留拒绝分母，不能改写旧门或重跑到绿。
完整混合负载、部署公平及正式D4/D5仍待完成；本项只交付可用观测与局部失败定位。
Schema 0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE。
