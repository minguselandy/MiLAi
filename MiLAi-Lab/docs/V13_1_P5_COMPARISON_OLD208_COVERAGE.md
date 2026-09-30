# v13.1 生命周期比较：原冻结版本覆盖与成本

2026-09-30。实际采集45/60条开发方法轨迹；30条完成全部消息，15条中断，另15条未执行。
完成消息不代表完整任务正确；最终回答、历史解释与记忆正文仍须单独评分。
[原始覆盖证据](../data/manifests/v13-1-p5-comparison-old208-coverage-results.json)记录完整分母、每臂成本、首个错误、SDK读回和实际退出证据。

| 方法／节奏 | 完成全部消息 | 已尝试／计划 | generation | generation tokens | embedding tokens |
|---|---:|---:|---:|---:|---:|
| StrongRawRAG matched | 5 | 6/6 | 55 | 288379 | 20657 |
| Receipt-RAG matched | 5 | 6/6 | 63 | 455942 | 18238 |
| Mem0-TraceEqual matched | 0 | 3/6 | 16 | 56012 | 4823 |
| Field-grounded matched | 2 | 6/6 | 106 | 559647 | 0 |
| StrongRawRAG native | 6 | 6/6 | 55 | 207509 | 22413 |
| Receipt-RAG native | 6 | 6/6 | 51 | 218510 | 17609 |
| Mem0-TraceEqual native | 0 | 0/6 | 0 | 0 | 0 |
| Field-grounded native | 4 | 6/6 | 75 | 353339 | 0 |
| Field-grounded 字段视图关闭 | 2 | 6/6 | 122 | 535961 | 0 |
| Mem0 手动 UPDATE 扩展 | 0 | 0/6 | 0 | 0 | 0 |

139个实际独立进程、45份 SDK 资源读回与完整响应逐条对账。新增543generation／2675299generation tokens／295embedding调用／83740embedding tokens，unknown0，Judge0。
原连续账本在本冻结版本收口时为7461generation／15742294generation tokens／538303embedding tokens。
冷进程 wall、CPU、存储和I/O只能按原记录的有限范围报告；终止编排父进程时，已在运行的子进程正常收口，其原回执保留，缺失的编排 wall 不补造。

23个真实 SIGKILL 退出由原进程 returncode=-9验证：W1十四次、W2六次、W3三次。
W3必须是实际持久 UPDATE；不把 ADD、READ、no-change 或未到达窗口计作 W3。
共同每消息12次生成额度跨重启累计：10条首个额度耗尽和2条输出截断均保留，不做补答或最好结果选择。

Mem0三条首个运行都在底层 Qdrant 关闭后采集快照，出现工程错误；因此停止全部受影响原生路径，保留另外15条未执行。
隔离副本的 Qdrant SDK／只读 SQLite 取证确认三个资源共有5条已持久化原生记忆，原文件逐个哈希不变、零HTTP；这不能把原中断结果改成通过。
修复在新源码中将证据采集放在所有资源关闭前，真实安装 SDK 的红测与通过记录单列。后续须另冻源码／队列，不能无说明合并为同一冻结版本结果。

这是六个已曝光、单工作流的开发故事，不是60个独立基础任务或12个新 Pilot-L。
数据目前只能描述本设置的覆盖、调用和机械效果，不能宣称 Field-grounded 优于简单回执投影，或把原生／matched 差异归为字段机制。
原生未支持的维护窗口保持未到达；同样存在合法当前查询，因此这些任务未证明长期记忆是必要条件。
完整目标 ACTIVE，Product NO_GO。
