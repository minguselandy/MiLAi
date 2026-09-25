# v9 本地复现

在 Lab 根目录使用固定上游 MERIT checkout（提交 `293933d96b1d1849e1f20d1bb324def5de9ed33f`）、本地 Host 和 embedding 模型目录。先检查 [配置模板](../configs/contextual-memory-v9-template.json) 的服务名、1024 维 embedding、thinking、容量与预算参数是否适合本机。准备脚本读取模板并用命令行地址及模型目录生成新配置；模板中的空身份字段不能直接用于运行。

```bash
uv run python tools/prepare_contextual_v9.py \
  --merit-root /path/to/MERIT \
  --host-dir /path/to/host-model \
  --embedding-dir /path/to/embedding-model \
  --host-url http://127.0.0.1:7860/v1/ \
  --embedding-url http://127.0.0.1:7861/v1/ \
  --output-dir artifacts/contextual-user-memory/v9-my-run \
  --budget-path artifacts/contextual-user-memory/v9-budget.json
```

默认准备只做本地文件哈希、上游原题生成与身份核对，**模型请求为零**。它从实际本地权重、metadata 和 tokenizer 生成 `model-weights.json`、`model-metadata.json`、`config.json`，并由当前源码生成 `freeze.json` 与 `selection.json`；不会载入旧 ignored artifact 作为原题。新生成的原生 `arc0-000` 必须是 5 个 episode、7 条公开消息，原 arc SHA-256 为 `32e50fc25c1ce473eccb5c0653e3867072d792c9aed80148236f9b0baff5d12f`，初始世界为 `221f4be1976ff8bc44ddc97b121dea6e15c22d79eff15dfe551a914342569b29`。每个输出目录必须为空；改源码或配置后用新的输出身份重新准备。预算文件独立于运行目录，现有 v9 账本不会被清零；另一环境可指定新的账本路径。

准备检查通过且 vLLM 服务就绪后，用已生成的文件直接启动真实 MERIT Host 工作流：

```bash
uv run python tools/run_contextual_merit.py \
  --selection artifacts/contextual-user-memory/v9-my-run/selection.json \
  --config artifacts/contextual-user-memory/v9-my-run/config.json \
  --freeze artifacts/contextual-user-memory/v9-my-run/freeze.json \
  --output artifacts/contextual-user-memory/v9-my-run/run
```

在上述命令加 `--prepare-only` 可只核对输入而不调用模型。准备脚本的 `--live` 仅适用于从**空输出目录**一步完成准备和真实运行；已有准备目录不会被覆盖。运行器保留每个 episode 的真实世界、工具、Host、维护和成本结果；中断轨迹单独保存，不接到改过的源码继续称连续通过。

固定文档消费者输入见 [四轮清单](../data/manifests/contextual-memory-v9-document-sequence.json)。`examples/contextual_document.py` 默认模式是确定性 wiring 样例，`model_requests=0`；`--live` 才连接配置中的 vLLM。文档四轮应从清单的原始 `initial_document` 和空 state 开始，按 `requests` 顺序逐新进程调用 `--live --config ... --workspace ... --state ... --output ... --session ... --turn ... --request-file ...`，每轮传入对应 `check_requirements` 的 `--required-section`。请勿把确定性样例、真实模型运行和只读查看历史 `artifacts/` 结果合并成同一种证据；现有 v7/v8 配置、制品和评分保持原样。
