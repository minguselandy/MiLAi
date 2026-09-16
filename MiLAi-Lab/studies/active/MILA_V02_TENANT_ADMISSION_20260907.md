# 数据库租户准入与公开故障链验证

状态：`TENANT_DATABASE_ADMISSION_VERIFIED_NOT_FULL_D3`，新增模型调用0。默认不启用
租户上限；本改动不改变完成优先的模型额度。Schema仍为`NO-GO FOR SCHEMA FREEZE`。

真实PostgreSQL先复现：池容量2时，租户A占满两条连接，租户B发生
`POOL_WAIT_TIMEOUT`；释放后B立即可读。全局有界排队不能单独防止该干扰。

Product增加可选`MILAI_DATABASE_POOL_MAX_PER_TENANT`，按已认证SessionContext中的
tenant UUID限制单个Database实例的在途获取/持有连接数。超限走现有503错误路径，原因
`TENANT_CONCURRENCY_LIMIT`，不增加队列或重试。异常、取消、连接等待失败均归还名额。
同租户更换actor不能绕过；API、Steward、worker仍各自独立池。详见Product ADR-047。

Product测试`runtime/tests/integration/test_database_tenant_capacity.py`使用真实PG、
独立角色凭据与两个不同租户的公开API handler。容量2/租户上限1时，A额外更新立即拒绝，
B仍能读取自己的完整State；无跨租户正文，错误鉴权仍为401。拒绝不产生新版本，释放后
原operation ID可正常提交v2并稳定重放。保留未启用模式的干扰复现，全部5项3.42秒通过。
这不是两个租户经网络网关的公平调度压测。

启用上限4/池8后，独占公开MCP组合故障回归通过：51条公开操作观察，另有2次capture，
18.581606秒，12对客户端区间重叠。同步CAS仅一个赢家；撤权后A的16次读取隐藏，B的16次
读取保真；worker/API被终止后，API不可用时不返回缓存正文，新进程可恢复合法版本和
赢家幂等回执。此回归是同租户两个项目，不冒充多租户网络负载测试。

配置：`configs/v02-tenant-admission-public.json`；产物：
`artifacts/v02-e2e-generality/tenant-admission-public-20260907a/`。
Product pin `34b63978039b2d0f0aab5fb9f1311138c0e897a62ebee2dd69b27a3835405146`；
锁`data/locks/v02-tenant-admission-product.lock.json`。历史SIM04–07锁和失败记录不覆盖。

验证命令及结果：

- Product `uv run pytest -q tests/unit`：987通过（11.12秒）。
- Product真实PG定向`pytest -q tests/integration/test_database_tenant_capacity.py`：5通过。
- Product `uv run ruff check src tests migrations`、`uv run mypy`（191文件）、`uv build`通过。
- Lab `uv run milai-lab-check-boundary`、`uv run pytest -q`（400通过，3.82秒）、
  `uv run ruff check src tests tools`、`uv run mypy src/milai_lab`、`uv build`通过。
- 独占API/worker进程已退出，PG已停止、未OOM；共享MCP/vLLM未改动。

没有迁移或API/schema/权限/Canonical语义变更；删除可选配置即可回退。不宣称任意租户数
公平、跨实例份额、整个服务SLO或全D3通过。未跑完整Product集成套件，本轮选择实际受影响的
连接容量、RLS、异常归还及公开保存/撤权/恢复路径。模型总账仍53请求、1,159,327 raw tokens，
付费0；正常开发例的语义成功与本项工程证据分开。
