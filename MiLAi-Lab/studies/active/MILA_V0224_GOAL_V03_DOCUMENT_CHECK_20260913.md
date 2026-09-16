---
goal_id: MILA-V02-24
document_kind: DOCUMENT_DELIVERY_CHECK
date: "2026-09-13"
status: DOCUMENT_CHECK_PASS_ENGINEERING_CHECKS_NOT_ALL_PASSED
gate_a: NOT_PASSED
new_experiment_allocation: 0
---

# v0.3 文档交付检查

本记录只验收[最新 Goal v0.3](MILA_V0224_Gate_A至E最新执行与研究_GOAL_v0.3_20260913.md)及四个导航入口。
没有修改实现、测试、Product pin、旧 Goal、R03/R04实际合同或原始校准证据，没有启动A–E正式实例或Provider模型请求。

| 检查 | 实际终态 |
| --- | --- |
| Goal本地链接、四个导航入口 | 可解析；新增交付记录与Goal互链另行复查 |
| 矩阵/资源 | PAIR与FOUR_ROOT均24B；D2双世界两根16、四根32；E含A最多448生成；条件总包络896/1152 |
| 旧文件保留 | v0.1、v0.2提案、v0.2.1差异、R03/R04、旧执行记录、Product lock共7文件hash未变 |
| 原校准终态 | terminal及其绑定16文件hash核对一致；不是完整语义/SQL独立审阅 |
| Markdown/diff | 无尾空白、围栏配对、改动导航diff检查通过 |
| `milai-lab-check-boundary` | exit0，包边界通过 |
| `mypy src/milai_lab` | exit0，39个source files通过 |
| `uv build` | exit0，sdist与wheel构建成功，输出到本轮临时目录而非覆盖原dist |
| `ruff check src tests tools` | exit1；未改动的`tests/unit/test_v0223_k2_entrypoints.py:37`有1项S603；本轮不修代码、不加忽略 |
| 全仓pytest | collected4049；1548 passed / 1 optional SDK skipped；320.07秒后主动SIGINT，exit2，其余未完成；不是全仓PASS |

工程命令在仅启用自身loopback、移除capabilities的网络命名空间运行，环境白名单与uv/HuggingFace离线开关开启。
测试进入历史`test_v0222_boundary_preparation.py`的真实冻结来源准备路径后耗时增加；
本轮目标只是文档，不继续扩成历史准入工程。仅向本轮精确确认的pytest进程发送SIGINT并取得终态，未停止其他实验或共享服务。
部分pytest通过数与本轮构建结果不签发R04工程证书、K3、Gate A或Memory准入。

本轮临时工程制品：[JUnit](/tmp/milai-v0224-goal-v03-checks-lYiqSIHo/pytest.xml)、构建输出目录`/tmp/milai-v0224-goal-v03-checks-lYiqSIHo/dist`。
临时目录不是长期冻结的Gate证据；本文件保留紧凑终态，原研究证据仍在既有evidence目录。
后续正式候选仍需绑定自身revision完成所有必要工程检查，不能借用本次部分通过结果。
