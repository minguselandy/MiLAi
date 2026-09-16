# MiLA V02 请求内文本分析复用

状态：`LOCAL_EQUIVALENCE_CONFIRMED / PUBLIC_CONCURRENCY_NOT_RETESTED`。
实际开发日期2026-09-07，文件名沿用冻结批次日期。完整P1/P2/P4及D4/D5未完成。

## 修改与边界

前轮普通读取审计中，240个span的解释约27.420ms CPU，是明确的计算开销。本轮将
词项、日期匹配范围/首次匹配、数字匹配、事件/偏好/当前意图信号的扫描放入纯文本分析。
一次解释调用内，相同全文复用这些扫描结果；先计数，仅保留实际重复文本的结果。
没有跨请求缓存，没有针对来源ID、字段位置或测试名称的分支。

来源时间归一化、speaker判断、事件anchor provenance、span/interpretation ID、具体解释
与绑定仍逐来源产生；不共享可变的最终解释对象。唯一文本不长期保留扫描结果。
权限门控及来源投影先于该计算，不缓存权限决定，不删首尾、不减少候选或改变State表示。
Runtime仍只执行原有确定性规则；没有加入语义模型或新State/Hint模块。

改动为Product `runtime/src/milai/application/evidence_semantics.py`及新增11项单元控制。
无API/schema/权限/Canonical/事务语义变化，无迁移；代码回退不需要转换持久数据。
Schema保持`NO-GO FOR SCHEMA FREEZE`。

## 局部候选筛选

Product忽略目录`runtime/var/v02-text-reuse/`保留原源码、候选和纯函数脚本及结果。
这些是Product自身诊断，不是Lab黑盒或服务SLO。第一版保留全部唯一文本扫描结果，
不同数字文本的tracemalloc峰值比原实现高约3.06MB；因此未采用该保留策略。
最终候选只保留重复文本，结果如下。每条件各实现交替10次，使用thread CPU中位数；
峰值另行执行tracemalloc测量，不与计时混用。

| 合成条件（60来源） | 原CPU ms | 候选CPU ms | 原/候选峰值 bytes |
| --- | ---: | ---: | ---: |
| 重复长文本，首尾完整 | 52.174 | 6.596 | 785059 / 286200 |
| 不同长文本 | 309.954 | 310.455 | 173012 / 169945 |
| 不同数字文本 | 430.092 | 433.222 | 33452866 / 33503730 |
| 混合语义文本 | 8.692 | 4.054 | 275214 / 245039 |

不同数字文本仍约0.73%额外CPU和50864 bytes额外峰值，本轮样本不证明差异统计显著。
重复文本有收益、不同文本基本无收益，不能概括为任意任务的固定加速比。
20个差分组合覆盖来源/时间/说话人、输入正反顺序、解释类型筛选和local anchor开关，
完整解释与两个compatibility profile的绑定相等。新增正式单元控制还明确断言当前意图
仅来自user、相对日期分别使用各来源时间、逐span provenance、输出修改和跨调用隔离。

## 真实请求验证与失败记录

复用公开h保留的1000条来源，自有PG按需启动；原API/worker/MCP未重启。Product自身
通过真实Flask公开路由、鉴权与PG执行，CPU affinity 0–1，模型调用0。

第一次两请求诊断的解释、绑定相等，但跨请求整个snapshot相等断言失败。两次请求各自
产生新的valid/system as-of，导致acquisition plan与requirement state摘要变化；不能
删除这些字段使比较通过。原两份响应、计划与失败日志全部保留，未记为成功快照控制。

修正诊断边界后，仅追加1个预先声明的请求：在同一次请求内，用相同时间、候选、门控
和决策材料，分别提供旧/新实现产生的完整解释与绑定构造snapshot。结果相等，完整
MemoryContext也与原实现响应相等。没有把完整HTTP响应宣称相同。

本轮共3个Runtime诊断请求，公开并发复测0。实际获取240 span、65种完整文本。
对捕获的同一材料交替10次，解释CPU中位数为27.509→7.455ms，完整输出每次均相等；
候选的一次43.146ms离群值保留在`request-result-v2.json`，未过滤。单次请求的wall/CPU
包含冷启动和额外差分计算，不能当作产品服务延迟或前后收益。

## 验证与后续

相邻测试59通过（0.60s），Runtime Ruff/mypy（189文件）/build通过。
Lab309通过（2.64s），边界/Ruff/mypy/build通过。Runtime完整真实PG1049通过、无跳过
（98.90s），回归目录`artifacts/v02-e2e-generality/p1-text-reuse-regression-20260906a/`。
SDK/MCP代码未改，未重复各自历史全量回归。

检查命令：Runtime `uv run ruff check src tests migrations`、`uv run mypy`、
`uv build`、配置真实PG各角色DSN后的`.venv/bin/pytest -q`；Lab
`uv run milai-lab-check-boundary`、`uv run pytest -q`、`uv run ruff check src tests tools`、
`uv run mypy src/milai_lab`、`uv build`。两仓`git diff --check`及新pin验证通过。
诊断/回归自有PG经inspect确认停止，回归API/worker进程不存在；客户端关闭，数据保留。
清理确认在回归目录`final-cleanup.json`，共享服务未改动。

新锁`data/locks/v02-text-reuse-product.lock.json`，源码pin
`624e305187eb52c6144f6b68797cf431311c2f413d13be8d4dd9fc6ab39ce2d9`，锁digest
`6ac1ec905a0b36a280dd8691ab7f55d963738fcd5d6071e2708e830e0b591a0e`。当前E2E/SIM02
候选同步，历史锁及h失败证据保留；SIM02新增模型授权仍0。

本轮局部收益支持保留该实现，但不足以证明从此前c8 P95 1306.270ms达到300ms。
下一步沿整条读取路径核算剩余计算需求，重点检查约22.940ms的绑定计算是否重复处理
同一需求约束；保持逐来源兼容性和归因。只有组成完整候选并有总成本证据后才公开复测，
不因这一局部优化立即再预置1000条数据。模型/Provider tokenize均0，不增加资源或门槛。
