# 当前版本固定读取与导入复测

状态：`STOPPED_AT_ARM_FAILURE`。读取保真且满足本次延迟门，导入容量门未通过，不能授予
完整D3。0模型调用，旧运行不覆盖，未扩大队列/并发、未重跑或删除首尾与引用。

配置`configs/v02-current-deployment-mixed.json`；运行命令：

```bash
PYTHONPATH=tools:src .venv/bin/python tools/run_v02_mixed_pair.py --config configs/v02-current-deployment-mixed.json --root artifacts/v02-e2e-generality/current-deployment-mixed-20260907a
```

两组顺序启动独立单租户Runtime/PG/MCP，各1000条State、三份512/2048/8192字节来源，
活动TASK/SESSION/PROJECT保持完整正文与引用；只读这些活动State，不冒充1000条范围检索。
每组12次预热，计划3轮×5秒，读取20/s，mixed额外导入10/s；客户端6读/2导入在途，
API线程/池8、CPU affinity2、PG2CPU/1GiB、零重试。租户可选上限未启用。
Product pin `34b63978039b2d0f0aab5fb9f1311138c0e897a62ebee2dd69b27a3835405146`。
比较装配后的活动State、来源输入hash与工具catalog，两组一致。缓存热度不声明严格等价。

| 组/轮 | 读取完成/计划 | 读取P95/P99 ms | 导入完成/计划 | 导入P95/P99 ms |
|---|---:|---:|---:|---:|
| baseline 1 | 100/100 | 16.316 / 75.131 | — | — |
| baseline 2 | 100/100 | 14.058 / 15.352 | — | — |
| baseline 3 | 100/100 | 12.306 / 13.329 | — | — |
| mixed 1 | 100/100 | 15.915 / 33.916 | 50/50 | 24.701 / 98.783 |
| mixed 2 | 100/100 | 15.670 / 18.986 | 46/50 | 217.813 / 476.888 |

延迟从计划发送时刻计起，表中分位数仅针对完成子集。mixed第二轮4次导入为
`CLIENT_CAPACITY_REJECTED`，没有发送至Runtime；不是服务端503、已提交失败或零延迟。
mixed第三轮未进入，不将其假装完成。已运行轮次500/500读取和96/100导入完成，完整原计划
为600读取/150导入。两轮配对不足以宣布整组退化门通过。

公开回执关联最慢导入：SDK调用475.828ms，Runtime application472.611ms，数据库持有
4.198ms、获取0.020ms、事务退出1.620ms。第二慢调用376.732ms，application373.530ms，
数据库持有5.063ms。主要耗时在数据库连接之外；这不证明具体文件系统/加密/调度根因。
源码`application/evidence.py`在数据库ingest前调用`adapters/blob_store.py`，后者包含
按内容锁、加密、文件fsync、rename、校验和目录fsync；下一步应区分这些步骤的实际耗时，
不能靠扩大池、删审计、关闭同步提交或省略必要落盘修复。

新增离线`tools/summarize_v02_import_readiness.py`，无新服务请求。96个导入逐项对应
公开outbox目标、evidence-search-v1版本与READY水位；由SDK调用开始至轮末READY响应给出
实际提交至就绪的保守上界，P50/P95/P99为2521.940/4921.619/5122.166ms。实际提交和实际
就绪时刻均未知，这不是精确索引延迟；上界超过5秒也不能反推实际就绪超过5秒。
从保存回执开始计时会遗漏提交至响应的时间，故不把它当完整提交延迟上界。
并发嵌套时物理请求不能仅凭包含区间唯一关联，保留`AMBIGUOUS_OVERLAP`，应用计时仍按
公开request ID指纹唯一关联；不猜测匹配，不把缺失计时当0。

证据在运行根的`pair-result.json`、各组`arrival-events.json`、`capture-receipts.json`、
`sdk-physical.jsonl`、`timing-correlated.json`，以及mixed的
`import-readiness-observations.json`。`terminal-fidelity-cleanup.json`复核两组材料与PG状态；
两组API/worker/MCP均退出，PG停止exit0、无OOM，共享服务未改。

检查：离线上界负控6通过；Lab全量406通过（3.85秒），boundary/Ruff/mypy（30文件）/build
通过。初次测试导入路径及Ruff格式问题已修正；实际并发数据揭示区间关联不唯一，修正后
保留不确定性。Product源码未修改，不借用旧Product测试数作为本轮执行。Schema仍NO-GO。
模型总账不变：53请求、1,159,327 raw tokens、付费0；SIM07语义成功与本轮服务失败独立。
