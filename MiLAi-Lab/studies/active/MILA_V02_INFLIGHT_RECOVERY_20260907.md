# 请求在途断线、操作确认与冷恢复

状态：`PUBLIC_INTERRUPTION_RECOVERY_VERIFIED_NOT_FULL_D3`。两条独占真实Runtime/PG链通过，
新增模型生成、tokenize及付费请求均0；完整服务负载和正式D4/D5尚未完成。

## 变更与故障边界

复用`tools/check_v02_durable_save.py`，增加配置路径参数和可选未确认State写入故障。
原配置默认仍按已确认保存后重启运行。`tools/v02_inflight_request.py`只用于Lab故障注入：
监听loopback，将一份完整请求转发至独占Runtime，故意不向客户端发送响应。
在以下两个确定性传输位置分别SIGKILL该API；没有引入Product代理或更改线上入口。

1. `AFTER_FORWARD`：HTTP请求正文完整发出后、客户端收到响应前。不能由发送完成推断
   服务端已接纳、已经进入事务或已经提交；事务内部阶段保持未观察。
2. `AFTER_UPSTREAM_RESPONSE`：故障注入器已收到Runtime的200，但客户端仍未收到响应。
   Runtime响应只是故障注入器的独立观察，不冒充客户端已确认回执。

客户端两次均为`RemoteProtocolError`，初始操作结果保持UNKNOWN。故障记录中的
`server_admission`及`commit_at_interrupt`未知字段表示客户端当时知识；第二条有独立
upstream 200观察，不能据此说服务端本身也一定不知道结果。
每条仅转发一次，记录请求正文hash及转发/中断时点，不记录token、授权头或原文日志。
不定点阻塞事务、不操作私有数据库、不宣称随机杀进程覆盖了所有事务内部崩溃位置。

## 两条实际链

新配置：`configs/v02-inflight-save-recovery.json`与
`configs/v02-committed-unacknowledged-recovery.json`。两条分别执行：

```bash
PYTHONPATH=tools:src .venv/bin/python tools/check_v02_durable_save.py --config configs/v02-inflight-save-recovery.json --root artifacts/v02-e2e-generality/inflight-save-recovery-20260907a
PYTHONPATH=tools:src .venv/bin/python tools/check_v02_durable_save.py --config configs/v02-committed-unacknowledged-recovery.json --root artifacts/v02-e2e-generality/committed-unacknowledged-recovery-20260907a
```

两条都先停worker，经公开HTTP保存512/2048/8192字节原文及带完整引用的State v1/v2。
随后以新operation ID、expected_version=2发出v3更新并注入故障。停止并重启独占PG，
启动不同PID的API，用新客户端读取、核对旧回执，并显式恢复同一操作。
显式恢复是测试合同中单列的动作，参数及operation ID保持不变，不是SDK隐式重试或盲覆盖。

| 观察 | 完整转发后中断 | 收到上游200后中断 |
|---|---|---|
| 客户端成功回执 | 没有，UNKNOWN | 没有，UNKNOWN |
| 重启后head | v2 | v3 |
| 同一操作显式恢复 | v3，replayed=false | 原v3，replayed=true |
| 再次幂等提交 | 同一v3身份，无v4 | 同一v3身份，无v4 |
| 旧v1回执与当前head | v1回放保持原版本；当前最终v3 | 同样保持独立 |
| 原文与引用 | 全部保留，首尾和字节数相同 | 全部保留，首尾和字节数相同 |
| 停止的加工任务 | 重启后仍PENDING，worker执行后READY且可检索 | 相同 |

本次第一条观察到此前操作没有可重放提交，第二条确认已有提交。区分依据是显式操作回执，
没有只凭head相等判定归属。除等待状态的公开408外，各正常业务调用均返回预期成功状态。
HTTP清单每条26个正常业务调用，另有1次故障请求向Runtime转发；两条合计54次业务Runtime
请求，不含服务准备/健康探测以及loopback relay入口请求，不能宣称这是全部网络调用数。
未运行模型，不推断模型将正确理解这些回执。

两条Product pin均为`97eaac6de36a96e903af0b41412a44e8c7715539ca12359b7be41f790a5754bc`。
每条运行前核对公开接口pin并保存runner/故障传输源码hash。第一条完成后增加第二种故障位置，
两条Host源码摘要分别保留，不用当前文件替代第一条执行身份。
运行器仅使用公开HTTP；这些结果补充既有MCP保存/撤权/CAS链，不替代所有Host自动恢复验收。

## 验证、收尾与剩余范围

5项故障传输测试通过：上游成功与断线、两个注入位置、正文保真、单次转发、成功响应不交付、
非loopback拒绝；负控拒绝重复转发、错误hash、客户端已成功、未确认进程结束和relay未退出。
未收到上游响应时不伪造第二位置的中断成功。完整Lab445 passed（4.37秒），boundary、
Ruff、mypy 30文件与build通过。开发中两处Ruff行长已修正。

终态审计核对正文hash、原文长度及首尾、State回执/版本、PENDING→READY→实际检索、PID与
Docker状态。两条API/worker/relay均结束，PG exit0、无OOM，保留卷与原始产物；共享服务未动。
证据入口为各运行根的`preflight.json`、`http-events.json`、`inflight-fault.json`、
`result.json`、`cleanup.json`、`terminal-audit.json`；同级
`audit-inflight-recovery-20260907.py`可离线复核。
故障请求hash可由已固定harness及回执重构核对，正常恢复请求参数通过runner控制逻辑关联，
不冒称取得了每条HTTP完整原始wire dump。

本项补齐了已测两种未确认传输结果的恢复证据，没有验证定点事务内部崩溃、断电、混合负载
SLO或租户公平，不把顺序有限故障检查当全D3通过。已确认后重启的历史证据仍独立保留。
Product代码、API/Schema、权限和Canonical均未改，无迁移/线上回滚动作。
Schema保持0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE。

下一步补完整服务负载出口：复核既有固定读取/导入的未完成配对与实际部署公平边界，
明确当前证据不足的项再做对应验证；不回到用户已接受的约525ms读取优化，不重跑SIM12。
