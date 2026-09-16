# MILA-V02-05：无候选时保留任务交付与已有State

2026-09-07（Asia/Shanghai）完成，沿用20260906文件标识。本次补充T04的工程编排证据，
没有改Product或Lab运行逻辑，没有模型生成。Product pin保持
`d6343d4b34c1f85ab40780cd12f4ac89fb5e34b3055b4d99edd8d1fb8084f337`。

## 已有取消路径

复核`DeadlineExpired`继承BaseException，能够越过保存过程的一般Exception处理。
已有取消测试明确检查写入中断后operation保持UNKNOWN且没有后续GET，未发现本次需要
修复的缺陷。相邻deadline与新编排测试合计15通过（1.31s）；这仍不是远端取消费用证明。

## 编排分支控制

新增4项测试直接调用当前`run_chain`和`host.checkpoint`，使用实际文件与脚本工作者：

- 缺失L1、L1为空白、缺失L2：正常任务report.md及完整来源保持；只调用一次State GET，
  不尝试候选写入；G保持COMPLETED，编排记录NO_COMPARISON_OPPORTUNITY，不追加G或A/B。
- 合格L1/L2正控：完成正常保存后，编排才调用A/B脚本工作者。这只验证分支调度，
  不将两个脚本返回值作为冷恢复或任务效果证据。

模型Provider构造在测试中被禁止，配置的模型额度仍0。没有分配文件或模型usage账目；
所有结果保留SIMULATION / NOT_EVALUATED / NOT_ENTERED标记。

## 真实State确认

独占Runtime/PG/公开MCP上预先创建合法State夹具H，包含既有正文和首尾字段。该夹具
不是自然Agent保存。脚本G生成普通任务report.md，不生成候选记忆文件，然后走当前
checkpoint及run_chain。结果为：

| 观察 | 结果 |
| --- | --- |
| 普通任务交付 | G为COMPLETED / task_delivered，report.md保留 |
| 候选保存 | NOT_ATTEMPTED，写入0 |
| 编排 | NO_COMPARISON_OPPORTUNITY，只有一次脚本G调用 |
| 已有H | payload、state_version_id、version=1完全保留 |
| 正常来源 | 完整source.txt及首尾不变 |
| 后续执行 | 没有第二个G，没有A/B，没有模型Provider/分配/usage |

全部4次显式MCP工具调用分别是夹具GET/UPDATE、checkpoint GET、独立最终GET。
夹具写入1与候选写入0分开记账，不能把fixture的保存当成本链候选保存成功。
MCP日志可见readyz GET200为1，POST200为12、POST202为4、GET200为4、DELETE200为4；
协议记录与工具调用不相加。Runtime API无逐请求访问日志，其物理请求数为null，不猜测。

本次验证的是已有实现的机械分支：合理不保存不使已交付任务失败，也不能填补保存后
冷恢复证据。它不证明模型自主判断“没有延续价值”的质量，不提供保存增量或通用性PASS。
T04因此更新工程证据，但保留模型选择未验证的边界。

## 验证与清理

Lab `uv run pytest -q`为324通过（2.68s）；boundary、Ruff、mypy（30文件）、build通过。
Product源码及当前Lab运行模块均未改，未重复历史Product回归。无schema/migration或
公开部署改变。自有API/worker/MCP均确认ABSENT、PG停止、资料保留，共享服务未动。
生成和Provider tokenize均0；开发劳动未计价，不称为免费实验。

原始计划、源码摘要、State回执、文件、编排结果及清理位于
`artifacts/v02-e2e-generality/d1-no-save-20260906a/`。
服务性能、真实Provider控制、正式D4/D5仍未完成，Schema保持
`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`。
