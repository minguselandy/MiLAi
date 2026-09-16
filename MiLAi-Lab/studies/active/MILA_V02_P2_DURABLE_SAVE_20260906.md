# MILA-V02-05 P2：保存落盘与冷恢复

状态：`MECHANISM_CHECK_PASSED / P2_PARTIAL`。没有新增模型生成或 Provider tokenize 调用；
完整 P1/D3 及 D4/D5 仍未通过。配置见 `configs/v02-durable-save.json`，运行器为
`tools/check_v02_durable_save.py`。

## 两个实际缺口及修复

1. Blob 原实现同步 staging 文件后重命名，没有同步目录。Product ADR-042 增加 leaf、
   tenant、blob root 及已配置父目录的同步；已有文件也重新核验并同步，覆盖先前失败后
   已存在的未确认文件。同步失败在 TX-01 前传播，不返回虚假保存回执。
2. 第一次实际完整正文直读发现末尾换行丢失。Runtime EvidenceIngestRequest 和 SDK
   EvidenceCaptureRequest 的全局去空白规则都会改写 content。ADR-043 为正文关闭该规则，
   保留标识符规范化；原始空白、换行和 Unicode 进入真实 content hash 与存储。
   没有删除测试首尾或缩短正文来通过。

文件同步不等于目录项同步，依据 Linux [fsync(2)](https://man7.org/linux/man-pages/man2/fsync.2.html)。
修复仍依赖已配置父目录、文件系统/设备同步保证及 PG 持久化配置。本轮没有断电测试。
原历史 Evidence 不重写；旧幂等操作若因现在保留的字节产生不同 fingerprint，允许明确冲突，
不能自动迁移或覆盖旧观察。没有 API 字段、工具、数据库实体、权限或 Canonical 变更。
无需 migration，未部署公网；Schema 仍为 `NO-GO FOR SCHEMA FREEZE`。

目录同步修复的首次运行 pin 为 `47bf30a30d2d6743a4844c1bd0956973c8f8517b4bfb721d42eb34867ecddb30`。
加入正文保真后的当前 pin 为
`e5dc1dafc1246153f753f5d6b2a71060a9ef6688ce70948bc0a796dac630a7a7`，
独立锁 `data/locks/v02-durable-save-fidelity-product.lock.json`。
旧锁和失败记录保留；当前工程配置及仍关闭的 SIM02 候选改指新锁。

## 公开接口冷恢复链

完整产物：`artifacts/v02-e2e-generality/p2-durable-20260906g/`。
这是顺序机制检查，使用一个本地 API 角色、一个 tenant，3 条合成 Evidence，正文分别
512/2,048/8,192 字节，首尾字段与末尾换行保留；State 引用真实 Evidence ID。
没有人工写数据库、没有生成模型、没有外部 embedding/rerank；worker 用既有 deterministic
hash provider，feature profile 为 BASELINE。进程 affinity 两核、8 API 线程、连接池最大8，
PG 2 CPU/1 GiB；Docker 默认地址池耗尽后改用明确 bridge 模式和本机端口绑定。
不把该网络配置与上一轮延迟结果当同配置效果对照。

23 次公开 HTTP 调用确认：

- worker 已停止后，保存返回 Evidence/blob/outbox 身份，立即 GET 完整正文一致；readiness
  返回 408 且 `projection_work_started=false`，没有把保存成功当索引已就绪。
- 同一 State 从 V1 更新到 V2，保存过程不等待 worker；State 不参与该索引，记 N/A。
- 确认回执后 SIGKILL 本轮 API，并停止/启动本轮 PG；新 API 进程和新 HTTP 客户端读取
  三份完整正文，与原提交一致。此时索引仍未就绪。
- 原 capture 显式重放返回同一 Evidence/blob/outbox ID；旧 State 操作重放返回 V1，
  另一次当前 GET 返回 V2。操作确认与 head 确认分开，没有把 head 不等于旧提交判作失败。
- 新 worker 进程执行一次有界周期后，三个 outbox 的 evidence 投影为 READY，公开 resolve
  返回对应 Evidence、`canonical=false`。第二个新 worker 周期后 readiness 仍为 READY。

三次保存的客户端耗时为 140.12/16.38/16.18ms，包含本轮同步和 HTTP 开销。样本只有3，
首请求含冷路径，且工程回归在另一独占 PG 同时运行；这些数值不构成 P95/SLO 或优化收益。
worker 被有意暂停，READY 观察是恢复后的上界，不能据此计算正常后台索引 P95。

## 失败与检查的归属

同级 `p2-durable-20260906a` 至 `f` 的失败全部保留，逐请求数见成功目录的 `attempts.json`。
这七次尝试共记录51次机制HTTP调用；健康检查、初始化、独立回归请求另列，不计作这51次。
其中 a 为 Docker 地址池耗尽且初版清理假定 services manifest 存在；b 为运行器使用了
不存在的 `MILAI_FORMATION_MODE`，改为公开 feature profile；c 为产品正文换行丢失；
d/e 为运行器把建 State 的201和更新的200混淆；f 为本机 Compose 不支持 `restart --wait`，
改用既有 `stop` 与 `up --detach --wait`。后续配置/脚本修复不覆盖这些记录。
上述启动/断言失败均不算完整链，也不是追加模型样本。

相邻 Blob/正文测试18通过；SDK完整179通过，MCP完整169通过/1默认PG跳过，Lab完整264通过。
Runtime直接PG故障测试通过：目录同步失败返回500，Evidence/outbox均0；显式重试提交后
可完整恢复正文，幂等重放不新增身份。Runtime全量首次为981通过/1失败，失败为上一轮
计时测试的logger在整套Alembic初始化后被禁用；已在测试局部恢复该logger并保留首次日志。
复用同一测试数据库再跑为978通过/4失败：三个测试被历史幂等/版本记录拒绝，另一个
降级被已存在的v0.2 continuation正确阻止，计时测试本身已通过。保留
`p2-durable-20260906d/regression-confirmation.json`，没有清空历史或放宽数据库保护。
随后复用b目录只初始化过、未有HTTP调用或pytest运行的独占PG，修正其无效配置变量后，
完整Runtime为 **982 passed / 0 skipped / 0 failed（94.03s）**，见
`p2-durable-20260906b/regression-fresh.json`。本次完整运行已包含公开SDK/OpenWorker包，
无可选包跳过。MCP真实PG生命周期另跑1通过（10.17s），见d目录确认日志。

SDK首次Ruff发现新增参数化测试签名超行宽，修正后通过；运行源码未因此变化。
Runtime/SDK/MCP静态、类型、构建以及Lab boundary/静态/类型/构建检查记录在
`p2-durable-20260906f/checks.json`，后续Ruff及Lab最终构建记录在g目录。

本轮补强保存和内容保真，没有重建已有 outbox、租约或 watermark。已有 Product 全量回归中的
旧租约拒绝、连续水位/dead-letter 和重放测试继续用于相应机械不变量；它们不等于本次公开
链覆盖了任意晚到任务或任意版本。固定读流量+导入、服务背压、租户公平性、完整混合负载
SLO仍待后续P1/P2/P4验证，不能因本链可恢复而授予P2整体PASS。

所有a–g尝试及独立回归的自有API/worker/PG均已停止，数据和原失败保留；a在服务启动前
失败的清理由 `cleanup-confirmed.json` 单独核实。g的 `deployment-confirmed.json` 确认PG
2 CPU/1 GiB、bridge网络且已停止。没有触碰共享vLLM或公共MCP，没有发布或提交共享修改。
