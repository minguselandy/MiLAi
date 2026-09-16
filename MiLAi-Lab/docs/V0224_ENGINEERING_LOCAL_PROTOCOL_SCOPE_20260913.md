# V0224 工程检查的本机协议测试范围

状态：**提案，等待独立代理审查；未执行工程全套或 HTTP 测试。** 用户已授权完整任务与代理审查，主代理批准本附加范围的设计方向。本文件只界定后续工程验证，不修改原 V0223、V0224 总 Goal、R02、已封存源码或当前校准合同。

当前默认 `uv run pytest` 包含真实本机套接字测试，不能声称字面意义上的全套零 HTTP。`pyproject.toml` 没有默认排除 integration/e2e；目前 `tests/integration` 只有说明，多个名字带 integration/live 的 unit 测试实际使用合成世界或 MockTransport。也不能给整个 pytest 进程安装实验用 `enable_cpu_network_guard()`：它会破坏合法 IPC 测试和明确要求父进程未安装该 guard 的负控。

本附加范围仅允许以下固定工程协议回归：

| 测试节点 | 单次允许行为 |
| --- | --- |
| `tests/unit/test_v02_native_mcp.py::test_unix_mcp_hop_preserves_http_bytes_and_closes_connections[ordinary]` | 在测试自建的 `127.0.0.1` 临时端口监听器上，经测试自有 AF_UNIX relay 发送一次固定 `POST /mcp HTTP/1.0`；无请求正文。 |
| 同函数 `[deep]` | 相同一次请求，仅验证深目录套接字路径。 |

请求的 Host 是上述测试自建端口。每项响应固定为 `HTTP/1.0 200 OK\r\nContent-Length: 4\r\n\r\ntail`。成功完整执行的限额是 **2 次本机协议请求、2 次固定响应**，每项一次，无重跑择优。原测试断言 `seen == [raw]`，并验证线程及连接关闭。失败时记录实际可证明的请求/响应数；不能由测试已开始推定已完成或零请求。

另允许 `test_mcp_upstream_closes_when_client_setup_fails` 创建同类测试自有监听器并关闭，**0 次 HTTP 请求**；允许 `test_deep_artifact_directory_can_bind_unix_socket`、`test_socket_bridge_preserves_half_close_and_returned_bytes` 等已有测试的 AF_UNIX/socketpair 本机 IPC。只限测试自建路径/连接，不访问已有 Product、vLLM、共享 MCP、Docker 或其他服务。

工程账务单列 `engineering_local_protocol_http_requests/responses`、失败/未知计数和逐节点终态；`external_http_requests` 与 `model_requests` 必须为 0。实验 A 的校准、K2/K3 仍保持原零网络/零 HTTP 边界，不能继承这个工程例外。原工程记录不改写，也不借旧 `new_real_http_requests=0` 标签推定这些本机协议字节不存在。

隔离采用新网络命名空间，仅启用其 loopback，然后清空 capability bounding/inheritable/ambient 集合并设置 `no_new_privs`。所有工程子进程继承该命名空间；没有宿主网络接口、路由或宿主 `127.0.0.1:7860` 服务。保留原 Python guard 的独立子进程测试，不给 pytest 父进程安装同名 guard。使用环境白名单，不传代理、凭据、外部 endpoint 或旧重型 profiler 开关。

2026-09-13 的安全能力探测：`unshare -n true` 实际 **exit 0**；`unshare`、`ip`、`setpriv` 均存在。该探测没有启用监听器、发送请求或运行测试。已只读看到 uv 缓存中的 hatchling 1.32.0、packaging、pathspec、pluggy、trove-classifiers；当前 venv 未安装 hatchling。**离线构建是否完整可用仍为 UNVERIFIED**，不能以目录存在替代 `uv build` 终态。缺缓存则停止并保留失败，不临时联网下载。

以下为最终 K3 实现封存后的推荐启动形态，**当前不执行**。`<fixed-engineering-launcher>` 必须换成经审查、固定的工程记录器；它逐条运行下面六条命令，记录实际 argv、白名单环境、start/log/exit/JUnit、源码与依赖绑定及成本。启动后先记录仅含本命名空间网络接口/路由和 capability 掩码的隔离证据，不保存完整环境。

```sh
env -i PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin \
  UV_OFFLINE=1 UV_FROZEN=1 UV_PYTHON_DOWNLOADS=never \
  UV_CACHE_DIR=/root/.cache/uv \
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
  PYTHONNOUSERSITE=1 \
  /usr/bin/unshare --net /bin/sh -c '
    set -eu
    /usr/sbin/ip link set dev lo up
    exec /usr/bin/setpriv --bounding-set=-all --inh-caps=-all \
      --ambient-caps=-all --no-new-privs "$@"
  ' engineering-netns <fixed-engineering-launcher>
```

工作目录固定为 `/cra/memory/mx_memory/MiLAi-Lab`，原六个逻辑命令不变：

```sh
uv run milai-lab-check-boundary
uv run pytest
uv run ruff check src tests tools
uv run mypy src/milai_lab
uv build
git diff --check
```

pytest 的实际 argv 可追加唯一测试临时目录与 JUnit 输出路径，并如实记录；不追加 deselect、`-m` 筛选或新 skip 来制造 full PASS。原 optional Host SDK `importorskip` 和已暴露外部证据不存在时的条件 skip 仍按实际情况逐项报告，不预填历史 skip 数。`UV_OFFLINE` 不会自动禁止测试代码联网，因此命名空间隔离与两项限定协议范围都不可省略。

全部工程命令应在当前夹具准备与计量结束、最终 K3 代码冻结后执行。任何命令失败、隔离未证实、超出本机协议限额、缺失终态或新的服务需求都不签工程 PASS。没有降低任何实验期限、余量门、矩阵或独立验收要求；本文件本身不授予 Gate A/K3 PASS，也不加入当前已封夹具依赖。

独立代理审查结果由单独记录绑定本文件的最终版本后生效。
