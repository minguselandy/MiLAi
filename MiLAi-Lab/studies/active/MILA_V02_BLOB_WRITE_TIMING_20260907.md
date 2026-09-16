# 原文保存分段计时与独立混合诊断

状态：`BLOB_WRITE_OBSERVABLE_LONG_TAIL_NOT_REPRODUCED`。上一轮约476ms导入长尾未在本轮
混合诊断复现；没有修复或性能收益结论，不授予完整D3。0模型/付费请求，原失败保留。

Product沿用默认关闭的request OperationTimer，增加blob整体写入、flock等待、编码、
文件fsync、目录fsync及已配置ingest observer的耗时/次数。公开合同仍为可选计时v1，
旧缺失字段不当0。保留原同步顺序、加密、错误传播、提交/权限/CAS语义；无新接口或迁移。
目录四级分别计数，内部时段嵌在整体blob时段中，不能重复相加或当纯设备I/O。

新锁`data/locks/v02-blob-write-timing-product.lock.json`，Product pin
`cb3edf1226376d5fcb17074f6322fa9b5ed4df3e10e1c10184f7b3abc03c167a`。
旧锁不覆盖。计时字段均不含文件路径、正文或身份。关闭已有计时开关可停止这些观测。
运行后纠正合同的一句边界说明：文件句柄open/close在fsync计时之外，Runtime实现未变。
保留运行时锁，新文档版本另存`v02-blob-write-timing-clarified-product.lock.json`；
不将旧运行标成新合同执行。规划来源准备同步修正文档，manifest保留未运行阶段的旧hash。

第一次计划仍为两臂同上限：1000 State，完整三份来源；读20/s＋混合导入10/s，3轮×5秒，
6读/2导入在途，API线程/池8、CPU affinity2、PG2CPU/1GiB，无重试，租户上限关闭。
配置`configs/v02-blob-write-timing.json`，产物`artifacts/v02-e2e-generality/blob-write-timing-20260907a`。
baseline第三轮P95 375.785ms，294读取完成、6次客户端未发送，按合同停止，mixed未进入。
最慢读445.506ms，其中应用438.242ms、DB持有437.786ms、事务退出435.714ms。这是本次
只读事务退出长尾，不应归因为尚未执行的混合导入或新增blob计时。

随后单独执行首次带计时的mixed诊断，不重跑baseline，也不将两个根拼接成通过的配对：
`configs/v02-blob-write-timing-mixed-only.json`，通过既有`service_calibration`执行，产物
`artifacts/v02-e2e-generality/blob-write-timing-mixed-20260907a`。硬件、完整数据、流量和
停止条件相同。300读取＋150导入全部完成；每轮读取P95 15.622/15.158/16.088ms，
导入P95 27.157/23.793/24.544ms。150目标outbox均有版本匹配的轮末READY；仍非精确索引延迟。

| 实际导入 | 调用ms | blob整体ms | 文件sync ms | 目录sync ms | DB持有ms |
|---|---:|---:|---:|---:|---:|
| 最慢，index3 | 45.082 | 35.805 | 24.959 | 9.354 | 5.847 |
| 第二慢，index13 | 40.281 | 14.216 | 4.265 | 6.227 | 22.705 |
| index104 | 35.776 | 28.236 | 24.695 | 2.071 | 3.337 |

第一行flock等待0.013ms、编码0.171ms。这解释这些具体调用，不能回填上一轮476ms
调用的缺失观测。没有再加负载或反复抽样来追逐长尾；保留可观察路径与未解根因。

验证：Product局部blob测试17通过，完整unit988通过（11.96秒），Ruff/mypy191文件/build
通过；真实PG计时开/关两条同步失败→零Evidence/outbox提交→显式重试/重放/逐字节直读
均通过（1.47秒）。首次fixture试图修改冻结Settings导致2失败，修正为构造前model_copy，
失败日志仍在`/tmp/milai-blob-timing-test-20260907a/initial-frozen-settings-failure.log`。
未重跑完整Product集成套件，受影响提交边界用真实PG定向验证。Lab406通过（3.72秒），
boundary/Ruff/mypy/build通过。所有独占API/worker/MCP退出、PG停止exit0无OOM；共享未改。

本轮新增观测使具体等待可追踪，但不改变此前SIM07开发例正确、State-first增费59.09%、
正式D4/D5未进入的结论。Schema仍NO-GO。后续推进正常规划任务的完整来源与验收准备，
不以本次未复现长尾冒充整体服务稳定性通过。
