# MiLA V02 绑定阶段的需求归一化与关系扫描复用

状态：`LOCAL_EQUIVALENCE_CONFIRMED / COMBINED_SERVICE_COST_PENDING`。实际日期2026-09-07，
沿用冻结批次文件日期。完整P1/P2/P4及D4/D5未完成，没有新增模型效果或通用性结论。

## 从实际开销选择修改

Product自身通过真实Flask公开路由、鉴权与保留的h PostgreSQL来源执行1个诊断请求，
捕获完整绑定输入。240条绑定未剖析CPU中位数22.527ms；cProfile本身使总时长升至47ms，
只用于调用归因。主要开销为240次关系判断及480次实体词归一化，并非仅角色model_dump。
完整绑定及MemoryContext与前轮一致。该实验是Product内部开发诊断，不是Lab黑盒/SLO。

实现只做两项复用：每个requirement的实体约束归一化一次；一次bind调用内，对相同全文
复用`classify_lookup_relation`的枚举结果。只有原有answer-bearing STATE_OBSERVATION
分支会按需调用它。每条interpretation的实体投影、类型、source/speaker、role、unit、
temporal、episode以及最终BindingCompatibility仍独立形成。没有共享可变的最终绑定
对象，没有跨调用缓存，也不因已经REJECTED而省略其他轴的判断。

源码`runtime/src/milai/application/evidence_semantics.py`，新增6项正式控制位于
`runtime/tests/unit/test_binding_scan_reuse.py`。不改权限、Canonical、事务、schema或公开
API，不需要迁移。代码回退即可恢复原计算方式，Schema保持`NO-GO FOR SCHEMA FREEZE`。

## 差分与成本

忽略目录`runtime/var/v02-binding-work/`保留baseline/candidate、实际输入、计划、原始
结果、profile和清理记录。实际及构造材料的16种组合覆盖两种compatibility profile、
type-compatible筛选、输入正反顺序，完整绑定相等。构造需求首次缺少硬speaker约束的
EXPLICIT_QUERY provenance被既有校验拒绝；修正测试输入，未放宽产品规则。

以下各实现交替10次，thread CPU中位数；tracemalloc峰值另测，不计入时长。

| 条件 | 原CPU ms | 候选CPU ms | 原/候选峰值 bytes |
| --- | ---: | ---: | ---: |
| 实际240绑定 | 22.252 | 4.726 | 539032 / 540773 |
| 混合需求与语义材料 | 106.957 | 84.976 | 5549724 / 5550384 |
| 不同长文本 | 100.747 | 100.739 | 132032 / 133949 |
| 不同短文本 | 3.370 | 3.258 | 402640 / 404557 |

收益依赖重复计算机会；不同长文本没有可见收益，不能推广固定加速比。新增正式控制
验证批量与逐对独立判断相等、同文本不同来源/角色/时间得到不同结果、修改一个输出
不影响其他输出，以及下一次调用观察新的需求和文本。

落入产品后，再执行1个真实请求：同一请求的时间/候选/门控材料下，旧、新完整绑定及
决策快照相等，完整MemoryContext与前轮相等。关系判断240→65次，实体归一化480→241次，
最终绑定仍240条。验证后的局部CPU中位数4.817ms，一次34.820ms离群值保留；不把
本轮两个单请求的时长差解释为端到端效果。累计2个Runtime诊断请求，公开校准0，模型0。

## 检查及交付边界

相邻44通过（0.60s）；Runtime真实PG1055通过、无跳过（98.44s），Ruff/mypy（189文件）/
build通过。Lab309通过（2.55s），边界/Ruff/mypy/build通过。SDK/MCP未改，未重复旧全量。
回归目录`artifacts/v02-e2e-generality/p1-binding-reuse-regression-20260906a/`。
Runtime执行`uv run ruff check src tests migrations`、`uv run mypy`、`uv build`，完整测试
使用真实PG各角色DSN和`.venv/bin/pytest -q`；Lab执行其AGENTS要求的五项检查。
两仓`git diff --check`及pin核验通过。自有诊断/回归PG经inspect确认停止，回归API/worker
不存在，客户端关闭；数据保留，共享服务未动。确认见回归目录`final-cleanup.json`。
新锁`data/locks/v02-binding-reuse-product.lock.json`，源码pin
`82e0bf3488d65654eaa87ad25a22577b9342366c4eab6c01d1c6f40ec3732321`，锁digest
`162b8e95af997cc9ea68858f894f642169909ecf7c8880523445fb8a6c735b35`。当前E2E/SIM02候选
同步；历史pin与公开h的c8 P95 1306.270ms失败结果保留。新增模型及Provider tokenize均0。

文本和绑定复用均已有局部等价/成本证据，下一步冻结这两个改动组成的候选，复用保留
材料测整条普通读取和并发CPU需求，再决定公开复测；不把两个局部加速比相乘或相加。
完整Context、来源及查询范围继续保留，不增加资源/负载或改变300ms停止线。
