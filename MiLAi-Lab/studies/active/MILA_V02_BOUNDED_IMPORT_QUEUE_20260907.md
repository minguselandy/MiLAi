# 有界导入等待：机制完成，当前服务门未通过

上一轮是实质进展：HTTP阶段计时及真实关联已完成，明确了客户端拒绝与文件同步的关系。
本轮按Goal §3.4/§6.2补一个可选等待位置，保留原在途容量；实际结果否定了“仅加一个
短等待位置就足以完成当前混合负载”的假设，不继续扩队列或重复到通过。

## 实现与冻结条件

Lab `v02_fixed_arrivals.arrivals`增加默认关闭的`queue_capacity`/`queue_timeout`。
启用时限制“在途＋等待”总数；等待期限从原计划到达时刻算，完成延迟包含等待。
队列满为`CLIENT_CAPACITY_REJECTED`，等候过期为`NOT_SENT_QUEUE_TIMEOUT`；均无dispatch，
不冒充服务端拒绝或未知提交。发送后超时/取消继续保留UNKNOWN。前一操作失败后等候请求
不再发送。终止时释放名额并等待已发请求本地清理，完整计划分母保持。

新配置`configs/v02-bounded-import-queue.json`在执行前冻结：导入容量仍2、等候容量1、
等候100ms（10次/s的一个到达周期）；读取不排队，容量仍6。其余20读/s、10导入/s、
3×5秒、1000 State、完整512/2048/8192字节来源、8线程/池、2 CPU和PG 1 GiB等均沿用。
L1 P95≤50ms、保存P95≤150ms、完整配对读退化比≤1.5未改。
Product pin仍`84ccec2a5ffeb7813667c378a59df593e13c4cc47b5cba815f75ff3ac1931dc4`，执行前验证。
这是新增Lab负载条件，不是产品性能修复或公网部署变更；旧零等待失败不改写。

## 结果与归因

根目录`artifacts/v02-e2e-generality/bounded-import-queue-20260907a`，终态`STOPPED_AT_ARM_FAILURE`。

| 臂/轮 | 完成 | 计划到完成P95 |
|---|---|---|
| baseline三轮 | 每轮100/100读 | 13.137 / 13.147 / 12.974ms |
| mixed轮0 | 100/100读，50/50导入 | 读16.967ms，保存26.610ms |
| mixed轮1 | 100/100读，48/50导入 | 读14.477ms，已完成保存260.355ms |

混合第三轮未进入。完整计划600读/150导入，实际500读/98导入；已进入轮导入分母100。
一次等待超时约100.756ms，另一次容量拒绝约0.533ms，二者未发送。等待中的另一导入成功：
等候60.912ms，调用13.216ms，总延迟74.537ms，等待没有从账本消失。

超时进入等候时import 85/86仍在途；公开回执与Runtime摘要唯一关联：
保存395.226/294.041ms，其中file fsync 381.402/276.622ms，DB acquire 0.017/0.021ms。
本轮即使仅看已完成导入，保存P95也超过原目标，不能通过删除未发送样本宣称达标。
fsync区间含调度，不是纯设备时间；不关闭同步、不扩大池、不变更源文件内容。

## 存储核查与终态证据

只读挂载核查表明工作区位于`/dev/vdc1` ext4，同设备亦挂载其他服务目录；`/var/tmp`
位于`/dev/vda1` ext4。不能仅由共享设备推断具体其他服务造成停顿。
一次独立有限文件诊断在两设备各60次写入、10次/s、最多2线程，保留相同三种字节数、
文件fsync/rename/目录fsync和读回hash核对。workspace file fsync P95 7.682ms、最大10.208ms；
system P95 4.188ms、最大6.715ms，长尾未复现。没有据此迁移服务或宣称系统盘修复问题。
诊断根`artifacts/v02-e2e-generality/fsync-devices-20260907a`；临时文件已删除，计划/结果保留。

配对终态脚本`artifacts/v02-e2e-generality/audit-bounded-import-queue-20260907.py`已执行：
两臂归一化State/完整来源请求/catalog一致，500次读取HTTP/MCP/Runtime唯一关联，
98个提交均公开READY。完整payload与版本由冻结runner断言，未声称有逐读wire正文转储。
独占API/worker/MCP/load client已退出，PG exit 0、无OOM、卷保留，共享服务未动。

验证：定向8通过（新增正常放行/等待过期/取消/失败4例）；Lab完整451通过、4.48秒；
`uv run milai-lab-check-boundary`、`uv run ruff check src tests tools`、
`uv run mypy src/milai_lab`（30文件）、`uv build`通过。Product源码未改，无需重跑其不受影响套件。
新增模型/tokenize/付费0，总账69请求、1,304,756 raw不变。Schema仍NO-GO FOR SCHEMA FREEZE。

下一步转向完整D3尚缺的真实私人用户热点/普通用户负载与恢复验证；私人项目共用部署tenant，
已有数据库tenant上限不能代替该用户范围的公平证据。当前存储负载条件未达标单独保留，
没有具体新证据前不继续增加队列、迁移磁盘或重跑混合配对。正式D4/D5仍未进入。
