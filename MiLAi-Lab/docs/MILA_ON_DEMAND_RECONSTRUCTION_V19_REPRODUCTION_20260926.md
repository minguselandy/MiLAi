# v19 复现入口

已完成的终态为 `STOPPED_STRUCTURED_RECONSTRUCTION_NOT_JUSTIFIED`，详见[结果](MILA_ON_DEMAND_RECONSTRUCTION_V19_RESULTS_20260926.md)。本页记录复现合同；发布不需要重跑模型、pytest 或 build。后续重复实验应使用独立 run ID、空 namespace 和新的输出目录，不覆盖本轮失败证据或清零连续账本。

## 固定身份

- 新[lock](../data/locks/milai-odr-v19.lock.json)：`b595101190d36f25f4b3a49456392eda547e650d7b0bf0f7bf1e456af9f2c77e`；52 文件 mapping：`1f22b6b7b032a647e360c140c61467763f7ce71b0a1fdd481d1c00ede88fbfaa`。
- [最终 freeze](../data/manifests/milai-odr-v19-final-freeze.json)：`aaf62b59475c8e8170a72cfa4af5c8c89a1cbeb7a8d6e5029ff2b06ae9ba4d63`，含 V0/packaging 回执、五分支 probe、10 组 zero-model prepare、预运行费用、输入/评分和空 namespace 身份。
- recipe：`milai-odr-request-reconstruction-json-action-v1`；transport：`json_action_reconstruction_v1`。显式 `--arm b1_control|freshness_only|odr`，没有隐式提升为有效主方法。
- 原 LangMem commit `9d033b47d9ce53e37e92c92241b0496c0278932e` 及 `uv.lock`；原 PostgreSQL/pgvector public Store、thread SQLite checkpoint 和业务 journal。
- 原 Host `Qwen3.6-35B-A3B-FP8`、tokenizer/weights identity 和 embedding `bge-m3`；不改 vLLM command、parser、thinking 或容量。路径模板允许指定实际 tokenizer 目录，其内容 hash 必须一致。

依赖由 `uv sync --frozen --group dev --group baseline-langmem` 安装。已存在的共享 `.venv` 足够本轮使用，没有为发布重新安装。

## 配置与运行

从[配置模板](../configs/milai-odr-v19.json)建立 ignored 的本地配置。填入原 tokenizer 的路径，并分别设置 trace、reconstruction_trace、sidecar、checkpoint、message_capacity、journal 和 budget 路径；各独立实例不要共用状态文件。DSN 仅从 `MILAI_LANGMEM_POSTGRES_DSN` 环境变量读取，不写入配置或 Git。使用原服务，不通过修改服务设置适配 schema。

查看零调用 schema：

```bash
uv run --no-sync python tools/run_milai_odr.py schema \
  --arm odr --fixture data/fixtures/milai_odr_v19_changed.json
```

以下以新建 `<run>` 为例；先 prepare，再以同一配置、输入和 lock 运行：

```bash
uv run --no-sync python tools/run_milai_odr.py prepare \
  --config artifacts/<run>/config.json --mode mechanism --run <run> --arm odr \
  --fixture data/fixtures/milai_odr_v19_changed.json \
  --mechanism-freeze data/manifests/milai-odr-v19-changed-freeze.json \
  --output artifacts/<run>/prepared.json

uv run --no-sync python tools/run_milai_odr.py run \
  --config artifacts/<run>/config.json --mode mechanism --run <run> --arm odr \
  --fixture data/fixtures/milai_odr_v19_changed.json \
  --mechanism-freeze data/manifests/milai-odr-v19-changed-freeze.json \
  --prepared artifacts/<run>/prepared.json \
  --output artifacts/<run>/run --stage <run>
```

retained/irrelevant 使用对应同名 fixture/freeze 和新的 run ID。真实调用并发为 1，所有请求和 embedding 连续计费。上游工具真实 seed/update，模型自己决定 search；不能用最终 rubric 驱动运行。数据与判定在[评价协议](../data/manifests/milai-odr-v19-evaluation-protocol.json)中预先冻结。

F-only 用 `--arm freshness_only`，普通 B1 用 `--arm b1_control`。本轮仅 ODR 三实例进行了正式运行；F-only/diagnostic/merit 的 prepare 回执表示零模型配置验证，不代表执行或通过。V5/V6 要求三个机制通过，V7 还要求 V6 无明显退化，本轮都未满足。

## 只读核对

```bash
uv run --no-sync python tools/inspect_milai_odr.py \
  --trace artifacts/<run>/reconstruction.jsonl

uv run --no-sync python tools/inspect_milai_odr.py \
  --sidecar artifacts/<run>/instrumentation.sqlite \
  --table requests --resolve-request

uv run --no-sync python tools/inspect_milai_odr.py \
  --sidecar artifacts/<run>/instrumentation.sqlite \
  --table request_material
```

inspection 的 accepted-trace 摘要仅描述已接受记录；发生拒绝/截断时，总模型分母应以实际 Provider trace 对账，不能只用 accepted 数量。本轮无拒绝，15 个 accepted 与 15 次正式请求一致。null 业务单独列出，0/0 grounding 不视为 100%。

本机原始证据位于 ignored `artifacts/on-demand-reconstruction-v19/`：`decoder-probe-r1`、`final-odr-{changed,retained,irrelevant}-r1`、`v19-budget.json`、环境前后回执和分析脚本。Git 中保留全部身份、紧凑结果和原始证据 hash；恢复原始 trace/DB 需使用已有本地证据，不能声称它们已随 Git 发布。

必要实现验证及唯一 build 的确切命令见[verification](../data/manifests/milai-odr-v19-verification.json)。保留其中已存在的旧 M1 测试断言不匹配，不把它漏报成全套通过。复现不需要持久 Decision State 或从分析日志恢复 reconstruction。
