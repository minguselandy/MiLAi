# MILA-V02-05：完整来源分句按需计算

状态：`IMPLEMENTED_ENGINEERING_VERIFIED / SERVICE_TARGET_UNMET`。
普通延后路径已不提前扫描全部span位置；完整来源、实际首个span及早期元数据校验保持。
它降低未消费完整语义时的准备成本，不证明模型效果、跨会话质量或整体服务达标。

## 实现与边界

`runtime/src/milai/application/evidence_semantics.py`把原分句循环抽成私有iterator，原
`_source_offsets`仍返回其完整list。规则、标点、缩写、Unicode、行边界及offset不变。
`prepared_evidence_spans.py`只取第一个真实offset验证来源，并保留完整正文及自有元数据；
实际materialize时用同一规则重新取得完整位置，保留原首个对象、排序和去重。
不存活generator，不在请求间共享来源/资格，不移除冻结副本的深复制或来源正文首尾。
没有新增模块、依赖、schema、公开API、权限、Canonical或事务语义；无需ADR/迁移，未部署。
回退只撤回这两处运行实现与相邻测试，不改持久化记忆或历史实验数据。

新pin：`56a0dab6df6dedd4540d3cc5a59fc1f9013505275e91cb7050b3d8eb56482e0c`。
锁：[v02-lazy-source-offsets-product.lock.json](../../data/locks/v02-lazy-source-offsets-product.lock.json)，
锁摘要`7739ecb40e63d5556ee5c90547603f6fcc05eca96da89e593cfb6aef0aa57322`。
E2E与保持关闭的SIM02候选配置引用新锁；旧pin/锁和旧公开结果保持原归属。

## 直接证据

Product忽略目录`runtime/var/v02-lazy-source-offsets/`保留原实现、离线候选、最终实现对照、
10请求结果、检查和清理。对照使用原真实采集的60份完整来源，并派生缩写/标点/换行/
Unicode组合，共1065种文本。最终offset、完整span及冻结副本均与保留原实现一致。

| 最终离线对照的CPU中位数 | 原实现 ms | 当前实现 ms |
|---|---:|---:|
| 准备＋冻结副本 | 6.961075 | 3.169761 |
| 后续完整消费 | 3.868910 | 7.504350 |

每种实现20次、交替执行；这些是局部回放，后续消费单列，不能声称计算总成本消失，
也不能把两组中位数之和当作实际逐请求总成本分布。

新增7项测试涵盖精确位置及“准备/冻结不扫描后续，完整消费恢复原文”的行为；已有
所有权修改、并发materialize、去重时序及早期资格/异常控制继续通过。首轮新测试把
`  ?!`的预期尾位置错误写成3，失败1、通过57；保留原实现回查确认旧新均为`(2,4)`，
修正测试预期后58项相邻测试通过（0.78s），没有删除末尾标点或修改分句迎合错误预期。

最终10次实际认证Flask路由/真实PG请求（warm、single、8并发）确认：

- 完整MemoryContext与保留母本相等。
- 计时路径未完整扫描offset、构造剩余span或物化raw semantics/snapshot。
- 计时后按每个请求自己的完整输入核对DTO及完整snapshot/digest，全部相等。

单请求wall/线程CPU为74.181454/35.941957ms。
8并发wall范围267.662330–403.126798ms，整批wall416.825241ms，
请求线程CPU合计369.520104ms、进程CPU466.209362ms。
单个86.235140ms CPU高值保留，原因未确认；不能将其直接归因于GC或删除出总账。
内部整批时间不是公开请求P95，也不是同条件随机配对的服务优化效应。
本轮未重跑公开压测；最新公开k仍属于8e345a71…旧pin，c8 P95为574.696638ms。

## 交付检查与未完成范围

独立真实PG根为`artifacts/v02-e2e-generality/p1-lazy-offsets-regression-20260907a/`。
`uv run pytest -q`：**1164 passed / 0 skipped，99.98s**。
Runtime `uv run ruff check src tests migrations`、`uv run mypy`（191源码文件）、`uv build`通过。
Lab boundary、Ruff `src tests tools`、mypy `src/milai_lab`（30文件）、build通过；
pytest **337 passed，2.80s**。类型检查范围不扩大到未配置的测试或tools。

本轮实际诊断请求10，离线0；回归/初始化请求另列。新增模型与Provider tokenize均0，
开发及设施成本不记作零。PG 2CPU/1GiB、Runtime CPU0/1、pool8/maxwaiting32、并发上限8
及300ms停止门槛保持。自有服务停止、数据保留；共享vLLM/公开MCP未改。

准入代码核对同时确认：`Database`仅有每池有界等待，Runtime身份来自固定tenant配置及
认证actor；Waitress按当前进程调度，不提供已证明的按租户公平份额。因此没有把
数据库背压、两个项目或角色凭证测试当作多租户公平性证据，也没有预先加入新调度平台。

完整P1/P2/P4和正式D4/D5仍未完成。下一步以当前仍实际发生的完整请求成本与服务隔离缺口
为依据，已延后的扫描不能重复计作可省成本。Schema保持
`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`。
