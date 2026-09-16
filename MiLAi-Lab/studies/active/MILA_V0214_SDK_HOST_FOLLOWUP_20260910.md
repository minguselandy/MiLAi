# V02-14 后续：Client 0.1.4 显式 Host 接线实验

## 执行前范围（2026-09-10）

用户要求继续后续实验，并明确功能实现优先、token 最后优化。本轮独立于已完成的
Goal v0.3 和原有 D5/D6 封存结果：验证真实本地实验 Host 使用已构建 Client 0.1.4
公开 helper 的完整链路，而不是继续使用 Lab 原型。不是外部商业 Host 或线上部署验收。

- 输入只复用已打开的 8 个合成开发 lineage、16 个阶段，不重新打开 confirmation，
  不读取 Horizon/Mem2Act 保护池。
- 原 H 提示、业务工具、选择策略、评分和 3 请求/阶段保持不变；不改 seed、不换题。
- Host 通过显式配置加载 SDK wheel；验证实际安装 Python 文件与冻结 wheel 相同。
  FileSources 产生 SDK 自己的 Binding/SourceRef/SourcePage/Coverage；每个冷 Host 使用
  一个 asyncio.Runner，遵守 SDK semaphore 的单事件循环约定。
- MCP 仍为隔离环境内的 0.1.15 / Client 0.1.3，Runtime 0.1.4 / deterministic_hash。
  Host 的 SDK 0.1.4 与 MCP 子进程的旧 Client 分开记账，不声称整套发布升级或 BGE 效果。
- 累计 raw token cap 为 null；实际 context 65,536、输出 4,096、final reserve 12,288、
  每阶段 300 秒、每阶段最多 3 请求、总计最多 48 请求、最多两个并发 Host。
- 外部业务仅生成待执行意图；仅 dev-06 按已有显式请求写入隔离 Note。无 State 创建、
  Canonical 直写、公网变更、默认切换或 Schema freeze。

先过零生成的 SDK 实装/并发/回执测试，再运行固定开发集。成功条件沿用 D5 的全部
16 阶段交付、澄清、冷恢复、长源选择性读取、隔离与账本门，并额外要求每个 Host
回执证明加载的确为 Client SDK wheel。失败保留，不改变旧证据、不自动重跑模型。

配置：`configs/v0214-sdk-host-development.json`。
新证据根：`/cra/memory/mx_memory/evidence/v0214/sdk-host-dev-v1-20260910`。

## 复现命令

在 `MiLAi-Lab` 中执行。证据目录必须不存在，避免覆盖；再次执行须分配新目录。
使用 `uv --with` 临时环境，不修改 Lab 依赖、既有服务 venv 或六个适配器锁。
首次在线依赖解析等待后改用缓存离线安装，未发送模型请求。

```bash
uv run --offline --locked --with ../MiLAi-Product/integrations/python-client/dist/milai_client-0.1.4-py3-none-any.whl python -m pytest -q
uv run --offline --locked --with ../MiLAi-Product/integrations/python-client/dist/milai_client-0.1.4-py3-none-any.whl python tools/run_v0214_e2e.py --root /cra/memory/mx_memory/evidence/v0214/sdk-host-dev-v1-20260910 --prepare-from /cra/memory/mx_memory/evidence/v0214/dev-prepared --config configs/v0214-sdk-host-development.json
uv run --offline --locked --with ../MiLAi-Product/integrations/python-client/dist/milai_client-0.1.4-py3-none-any.whl python tools/run_v0214_e2e.py --root /cra/memory/mx_memory/evidence/v0214/sdk-host-dev-v1-20260910 --installed /cra/memory/mx_memory/evidence/v0210-v05/e3a-20260909
uv run python tools/summarize_v0214_e2e.py --root /cra/memory/mx_memory/evidence/v0214/sdk-host-dev-v1-20260910
uv run python tools/finalize_v0214.py --root /cra/memory/mx_memory/evidence/v0214/sdk-host-dev-v1-20260910
```

SDK 的来源清单使用其公开默认 `kind=SOURCE`、`product_populated=null`；这不是隐藏的
记忆填充提示。虽然 H 提示/选择策略保持原样，本轮也不当作与昨日结果严格控制的因果比较。

## 结果

终态：`SDK_HOST_DEVELOPMENT_PASS_KEEP_A0`。已有 D5 全部门重算通过，且每个冷 Host 的
`host-runtime.json` 与预封存 SDK 身份一致。证明本地实验 Host 的真实 opt-in 接线可用，
不把这轮已打开开发集回归当作新的独立 confirmation。

| 项目 | 实际结果 |
| --- | --- |
| 固定任务 | 8 lineage / 16 阶段；15 正确交付 + 1 正确澄清 |
| SDK 身份 | Client 0.1.4，15 个实际安装 Python 文件逐一匹配冻结 wheel；16/16 Host 相同 |
| 无需记忆 | 两阶段 source calls 0、save NO_CHANGE |
| 短/长历史 | 两类均两阶段正确；长源每阶段选中读取 1 页，LEXICAL_SEARCH / PARTIAL，未全读 |
| 歧义 | 实际询问 maple-east / maple-west，意图数组为空；收到当前选择后正确交付 |
| 新观察 | 阶段 0 cedar-v1，阶段 1 cedar-v2；没有沿用旧 bucket |
| Note 冷恢复 | 显式 ADD_NOTE 实际 COMMITTED；新 Host 无 source 文件，经公开 inventory/read 恢复正确配置 |
| 并发 | 两任务、两个阶段真实 Host 重叠 9.234s / 9.317s；绑定和来源回执隔离 |
| 成本 | 29 次本地生成 / 194,079 raw tokens；92 次公开 MCP 调用；Host CPU 25.112s |
| 对账 | Provider HTTP/payload/tokenize/usage 与预算账本一致；unknown 0、violations 0 |
| 清理 | 16 Host 和 API PID 均不存在；本轮精确 project 的 PG 容器 exited；证据根 0700，卷保留 |

这轮所有非 Note 显式保存阶段均 NO_CHANGE；没有真实业务操作执行。16 个阶段耗时
5.182–9.351 秒，含 Host 已定义的阶段路径，不是服务独立延迟测量。GPU/货币等未测量
成本不由 raw token 或缺少计数器推断为零；没有成本优于旧 helper 的结论。

旧 D0–D7 七批仍为 133 请求 / 877,655 raw，本轮另外 29 / 194,079。两者算术合计
162 / 1,071,734，但未改写原 `final-accounting.json`、Goal v0.3、manifest、案例或结果。
本轮没有失败模型请求、重试或换题。

## 工程验证与交付

- 针对 SDK 接线、旧 Host 和机械边界：48 passed。
- 默认 Lab 环境：751 passed / 1 optional SDK-wheel skipped，9.52s；不强迫 Lab 依赖 Product。
- 实际 SDK wheel 临时环境：752 passed，9.54s，零跳过。
- `uv run milai-lab-check-boundary`、`uv run ruff check src tests tools`、
  `uv run mypy src/milai_lab`（39 文件）、`uv build` 均 PASS。
- 本轮没有修改 Product SDK/MCP/Runtime 源码或适配器锁，所以未重复六个无关包的完整门。
  真实 PG/MCP 使用的是上表所述冻结旧服务包，不是新 Client 接管 MCP 子进程的验证。

实现只在 Lab 的 Host runner/来源适配器加入显式类型选择和单事件循环生命周期，
新模块 `tools/v0214_host_runtime.py` 验证公开 SDK wheel，不给 `src/milai_lab` 添加 Product
依赖。未配置时继续使用 LAB；退出本次 `uv --with` 环境即可结束 SDK 选择，不需数据迁移。
SDK 公开模块 SHA256：`3689b1fe94e36344ab8a8011181c342acbf6b476d10fdadf7445a10d64a391a1`。

证据根内的 `manifest.json`、`host-runtime.json`（各 phase）、`summary.json`、
`stage-gate.json`、Provider 和公开调用回执保留完整复算路径。

仍未验证：外部商业/第三方 Host 接线、线上 BGE、服务端饱和、大规模远程源、保护池泛化。
A0 默认不变；Schema 始终 `0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE`。
