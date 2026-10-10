# Hindsight 0.10.3 原生服务的本地部署约定

本页记录独立原生服务的入口、配置和资源边界，不是实验结果。核查对象为实际
`hindsight-api-slim==0.10.3`、`hindsight-client==0.10.3` 和 `pg0-embedded==0.15.2`。
本次独立安装、禁网配置核查及机械 fixture 没有启动 Hindsight / PostgreSQL，没有调用 Qwen、BGE 或 Judge。
服务部署、原 HTTP 租约和真实模型调度由 Root 管理。

## 官方入口与配置来源

官方 CLI 的前台入口为安装环境的 `bin/hindsight-api`，公开 entry point 为
`hindsight_api.main:main`。独立服务以 `--host 127.0.0.1 --port <独立端口> --workers 1`
启动。配置定义在该版本安装包的 `hindsight_api/config.py`，初始化和退出路径分别在
`engine/memory_engine.py`、`main.py` 与 `pg0.py`。安装依赖使用官方
`hindsight-api-slim[embedded-db]==0.10.3`； SDK、pg0 和其实际依赖版本须保存到运行环境清单。
一般配置说明见[官方部署资料](https://hindsight.vectorize.io/developer/deployment/configuration)。

当前本地集成改用官方公开程序入口：`MemoryEngine(embeddings=OpenAIEmbeddings(...,
max_retries=0))` → `create_app` → `uvicorn.Server`。该版本环境 factory 的 OpenAI 分支
没有传递 `embeddings_max_retries`，原生 SDK 默认重试3次，因此仅设置下方环境变量为0
不能证明实际关闭重试。公开构造参数将其明确设为0，保留原生提取、批处理、召回和重排。
这是声明的本地部署适配，不称原 CLI 的原样运行。程序入口使用显式环境、不加载 dotenv；
在同一事件循环保留启动失败的 `memory.close()` 清理，并由 Root 核对真实 UID 残留进程。
当前专属用户、完整解释器及独立192包安装已完成。实际UID996禁网核对了
API0.10.3／pg0 0.15.2／Python3.11.13、维度1024／native embedding重试0／并发1／batch16、
worker槽1／consolidation保留0，未覆盖HOME；官方pg0二进制help可执行。
实际依赖清单及回执位于ignored `artifacts/baseline-alignment/native-installed-admission-e71440c`。
网络／模型请求0，API／DB尚未启动，不能据此宣称原生闭环完成。

该版本官方 CLI 调用 `load_dotenv(find_dotenv(usecwd=True), override=True)`。
从当前目录向上发现的 `.env` 会覆盖已导出的环境变量。因此运行目录及祖先中的 `.env`
必须受本次冻结配置控制。真实 URL、短期 bridge key、环境文件和进程产物只放 ignored 目录。
清理继承的旧 Hindsight / provider 配置，并保存实际有效配置；不能仅根据父进程导出的值
宣称原生服务已经使用 bridge。

## embedded DB 的实际目录与用户

pg0 0.15.2 的官方发布对应 commit
[`29191fbf00f218d09f271c33c3d8ec5525c3c4ab`](https://github.com/vectorize-io/pg0/tree/29191fbf00f218d09f271c33c3d8ec5525c3c4ab)。
该版本 [`src/main.rs`](https://github.com/vectorize-io/pg0/blob/29191fbf00f218d09f271c33c3d8ec5525c3c4ab/src/main.rs)
的 base directory 固定为运行用户的 `~/.pg0`：

- 数据及状态：`~/.pg0/instances/<唯一实例>/data` 与同目录的 `instance.json`。
- PostgreSQL 安装缓存：`~/.pg0/installation/<PostgreSQL版本>`。
- 临时文件：Rust 的系统临时目录；为服务指定本次独立 ignored `TMPDIR`。

没有 `PG0_DATA_DIR`、`PG0_CACHE_DIR` 或可替代这两者的 Hindsight 目录环境变量。
pg0 公开 Python SDK 支持 `Pg0(data_dir=...)`，但 Hindsight 0.10.3 的 embedded 包装只传
instance name、账号、端口和 PostgreSQL config，不传 `data_dir`。`pg0://` 的 query 参数
进入 `postgresql.conf`，不能用它虚构数据或缓存目录配置。

PostgreSQL 不能以 root 用户运行，见[pg0 官方说明](https://github.com/vectorize-io/pg0#postgresql-cannot-run-as-root)。
使用实际非 root 服务用户及其独立、可写的真实 passwd home；已有专属用户可以复用。
若 Root 创建专属实验用户，其真实 home 放在本次 ignored 目录，并按实际 UID 执行服务。
保持正常 home 解析，不通过改写 `HOME` 模拟隔离。每个运行根使用唯一 pg0 实例和独立
合法 schema；仅换 bank ID 不能隔离旧后台任务和原生 DB。

如果 Root 改用公开 `Pg0(data_dir=...)` 独立启动原生 DB，再把实际 PostgreSQL URL 交给
Hindsight，安装缓存仍位于该用户的 `~/.pg0/installation`，而 DB 生命周期由 Root 控制。
不能把已经运行的 DB 误称为由 Hindsight 创建并关闭：该版本只跟踪它自己启动的 pg0。

## 冻结配置

下列值使用实际 0.10.3 环境变量名。占位 URL 和 key 在运行时取
`HindsightModelBridge.base_url`（含 `/v1`）及 `.api_key`，两类请求均通过同一个 bridge
进入原 `VLLMClient` / `RunBudget`；不能直接交付上游模型端点。

```dotenv
HINDSIGHT_API_DATABASE_BACKEND=postgresql
HINDSIGHT_API_DATABASE_URL=pg0://<唯一实例>
HINDSIGHT_API_DATABASE_SCHEMA=<唯一合法schema>
HINDSIGHT_API_VECTOR_EXTENSION=pgvector
HINDSIGHT_API_TEXT_SEARCH_EXTENSION=native
HINDSIGHT_API_SKIP_LLM_VERIFICATION=true
HINDSIGHT_API_LLM_PROVIDER=openai
HINDSIGHT_API_LLM_MODEL=Qwen3.6-35B-A3B-FP8
HINDSIGHT_API_LLM_BASE_URL=<BRIDGE_BASE_URL>
HINDSIGHT_API_LLM_API_KEY=<BRIDGE_API_KEY>
HINDSIGHT_API_LLM_MAX_CONCURRENT=1
HINDSIGHT_API_LLM_MAX_RETRIES=0
HINDSIGHT_API_LLM_TIMEOUT=300
HINDSIGHT_API_LLM_TEMPERATURE_RETAIN=0.1
HINDSIGHT_API_LLM_TEMPERATURE_CONSOLIDATION=0.0
HINDSIGHT_API_RETAIN_LLM_MAX_CONCURRENT=1
HINDSIGHT_API_RETAIN_LLM_MAX_RETRIES=0
HINDSIGHT_API_CONSOLIDATION_LLM_MAX_CONCURRENT=1
HINDSIGHT_API_CONSOLIDATION_LLM_MAX_RETRIES=0
HINDSIGHT_API_RETAIN_MAX_COMPLETION_TOKENS=32768
HINDSIGHT_API_CONSOLIDATION_MAX_COMPLETION_TOKENS=32768
HINDSIGHT_API_EMBEDDINGS_PROVIDER=openai
HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL=bge-m3
HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL=<BRIDGE_BASE_URL>
HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY=<BRIDGE_API_KEY>
HINDSIGHT_API_EMBEDDINGS_OPENAI_DIMENSIONS=1024
HINDSIGHT_API_EMBEDDINGS_OPENAI_BATCH_SIZE=16
HINDSIGHT_API_EMBEDDINGS_MAX_CONCURRENT_REQUESTS=1
HINDSIGHT_API_EMBEDDINGS_MAX_RETRIES=0
HINDSIGHT_API_RERANKER_PROVIDER=rrf
HINDSIGHT_API_RERANKER_MAX_RETRIES=0
HINDSIGHT_API_WORKERS=1
HINDSIGHT_API_WORKER_ENABLED=true
HINDSIGHT_API_WORKER_MAX_SLOTS=1
HINDSIGHT_API_WORKER_CONSOLIDATION_RESERVED_SLOTS=0
HINDSIGHT_API_WORKER_MAX_RETRIES=0
HINDSIGHT_API_CONSOLIDATION_MAX_ATTEMPTS=1
HINDSIGHT_API_CONSOLIDATION_LLM_PARALLELISM=1
HINDSIGHT_API_RETAIN_MAX_CONCURRENT=1
HINDSIGHT_API_RETAIN_SUBBATCH_CONCURRENCY=1
HINDSIGHT_API_RECALL_MAX_CONCURRENT=1
HINDSIGHT_API_ENABLE_OBSERVATIONS=true
HINDSIGHT_API_ENABLE_AUTO_CONSOLIDATION=true
```

`HINDSIGHT_API_EMBEDDINGS_MAX_RETRIES=0` 是声明值；本地实际 SDK 禁用重试的依据是
上述原生 `OpenAIEmbeddings(max_retries=0)` 构造参数，不能仅引用这个环境变量。

原生 retain 的默认实际 temperature 是 `0.1`，consolidation 为 `0.0`；不能用全局
`HINDSIGHT_API_LLM_TEMPERATURE=0` 覆盖后还宣称保留作者原设置。
thinking / schema / tools 等依原生设置与显式冻结的 `HINDSIGHT_API_LLM_EXTRA_BODY` 传递，
bridge 不重写。留存输出上限 32768 是本地资源配置；省略 output limit 的原生请求只使用
已验证的部署有限上界做账本预留，不把预留值写回实际 HTTP。
本地配置明确传递 `chat_template_kwargs.enable_thinking=true`，不同阶段参数仍分别报告。
已按实际安装包只读核对36个声明环境变量，均有解析路径；温度、thinking及阶段重试／并发设置
由原生配置继承。32768控制retain和主consolidation batch，并不覆盖全部原生生成：
原生consolidate_dedup调用未给output limit，bridge仅按部署context65536做有限费用预留，
不将其写回请求。consolidation保留原生自适应二分，retry0／attempts1也不等于整个操作只有一次生成。
因此不能将所有Hindsight内部调用称为output32768，或将其与共同Reader温度1.0合称相同完整配置；
实际wire、调用数和usage仍以运行回执为准。

显式 dimensions=1024 避免未知模型的初始化 test embedding；skip verification 禁用 LLM
启动探针；rrf 不初始化神经重排模型。单 worker slot 必须将 consolidation reserved slots
设为 0，保留可供 graph / vector maintenance 使用的 shared slot。设为 1 虽通过配置校验，
却会使其余任务拿不到 shared slot。这里使用原生 rrf，属于声明的本地适配，不能写成作者
默认 crossencoder 的严格复现。真实吞吐、费用和语义效果仍待实际原生运行观察。

## 同步完成与关闭

原生 `retain(async=false)` 完成事实写入后仍可能排入 consolidation、graph 和 vector
maintenance。薄适配通过公开 bank stats（refresh）及 pending / processing operations
等待：`pending_operations`、`pending_consolidation`、pending total、processing total
全部为 0。等待 deadline 为 300 秒，并保存每次实际状态；failed counters 非 0 仍报告失败，
不会补发 retain。未知状态、超时和丢失响应不恢复为成功。

先完成所有 bank 的原生等待并关闭 SDK，再由 Root 关闭独立原生服务、bridge、原客户端
及原租约。pg0 SDK 的 `stop` 使用 `check=False`，非零退出码可能没有上抛；服务打印
`pg0 stopped` 不能代替实际关闭证据。PostgreSQL 的子进程可能脱离 API 的进程组，Root
还需核对专属服务 UID 下的实际存活进程和 DB ownership。bridge 的
`resources_settled` 只说明已退出的模型 HTTP；完整 HTTP 错误或缺 usage 可以是已闭合
HTTP，但仍停止新请求并保留原错误 / 未核定费用预留，不代表原生服务已经闭合。
重开时，历史已 dispatch 却没有完整响应或合法 usage 的实际 transport 阻止 bridge 启动，
不重试、不退款、不构造 usage。原生资料和回传顺序保持原样。
