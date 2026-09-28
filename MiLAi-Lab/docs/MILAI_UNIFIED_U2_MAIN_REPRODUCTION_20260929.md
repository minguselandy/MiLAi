# U2 首张主表复现说明

对应[结果报告](MILAI_UNIFIED_U2_MAIN_RESULTS_20260929.md)及[逐项机器证据](../data/manifests/unified-v8-v9-u2-main-results-20260929.json)。复现是新执行身份；不能覆盖原失败、状态、数据库、冻结文件或连续账本。本文不自动授权新的模型下载、部署或实验。

## 固定版本和环境

实际执行为 `e6df2f5d914c3ea2f08ce34f0887749e6f0c30dc`，方法源码为其前序 `795725a297fb1ef5f9d7bb712b3500d5b72546c0`。在独立checkout使用执行版本，不要求最新源码继续同时满足旧锁。

| 资源 | 实际身份 |
| --- | --- |
| MERIT | `293933d96b1d1849e1f20d1bb324def5de9ed33f` |
| MemSyco-Bench | `fd1f0f0270f35467aace1f9c0bf6a8bfb9b87221` |
| Mem0 | `f8082a7345dadd9e042ebbc40b57b1498c8f6d63`，实际SDK/pin，ADD-only |
| Foundation | Python3.11.13、OpenAI3.19.2、LangMem0.0.30、LangGraph1.1.10、mcp2.1.1 |
| Mem0 external | Python3.11.13、mem0ai2.1.0、OpenAI3.19.2、Qdrant1.19.1、FastEmbed0.8.1、spaCy3.8.16/en_core_web_sm3.8.0 |

环境完整包/文件身份见[外部环境清单](../data/manifests/unified-v8-v9-u2-external-environment-20260929.json)和[工程检查回执](../data/manifests/unified-v8-v9-u2-engineering-checks-20260929.json)。使用已有reference源码与资产，原运行期间0下载/安装。FastEmbed BM25资产是该锁定版本的词法资源，不冒充新学习模型。

Host使用[独立R2服务](../data/manifests/unified-v8-v9-host-service-r2-ready-20260928.json)：7862，Qwen3.6-35B-A3B-FP8，vLLM0.27.1，TP2/GPU2—3，65536，gpu_memory_utilization0.88，auto tool choice＋qwen3_coder，reasoning parser qwen3，thinking=false。container `b144371a277fb382ec5ffd1ea1b440c145bf094fc6ee04011fcc0699850f687c`；image `sha256:e0cfcfcb9b86e2c2d0d52a93689773f20f380cb8e050a24ce550c44f6f55c5eb`。旧7860不参与本主表。

模型小资产来自 `/cra/qwen36-35B`，tokenizer三文件哈希在[配置](../data/diagnostics/unified-v8-v9-u2/native-common-config.json)。完整权重revision未独立核实，模型名与小文件哈希不替代完整权重校验。Embedding7861为bge-m3/1024维；reranker未使用。Host/reader温度0、输出4096，摘要2048，Judge1024。MERIT每消息总生成上限12，HTTP串行1。服务版本/硬件/动态日期及推理非确定性仍可使新运行不同。

## 输入重建与信息权限

[MemSyco选择清单](../data/manifests/unified-v8-v9-memsyco-subsets-20260928.json)中的development有60题、54来源组，三个任务各20题。按原生ID、原行/完整历史/runtime输入哈希核对现有官方数据，不按答案重选。60个不同历史分别冷建，各方法先全部建库再全部查询。原数据不随结果仓库再分发；其代码许可不能替代尚未单独核实的数据再分发许可。

[MERIT规则](../data/manifests/unified-v8-v9-merit-selection-policy-20260928.json)和[18个输入清单](../data/manifests/unified-v8-v9-merit-development-inputs-20260929.json)固定三域、easy/hard各3个、seeds11—28。用固定上游的 `DOMAINS[domain].generate_suite(**generator_arguments)`，保留完整五episode；不修改checker或工具。原始arc字节为：

```python
json.dumps(dataclasses.asdict(arc), ensure_ascii=False,
           sort_keys=True, separators=(",", ":")).encode()
```

初始world为 `arc.make_world().dump_json().encode()`；关闭连接后分别核对每份清单的SHA256。官方生成器内部leak check仍执行。新的本机绝对路径需写入独立复现manifest并重新冻结，不能伪称仍有原选择文件哈希。

含gold的原始文件仅供离线prepare/scorer。运行器只接收脱敏的TaskInput/ArchiveInput；目标问题不参与归档形成，未来episode不进当前请求。程序按benchmark边界提交归档，不将历史命令重演为新业务授权。owner、来源、完整有序历史和方法身份共同确定cache key。

## 准备、冻结和运行

从Lab目录使用已有 `tools/run_unified_benchmarks.py`。其余四方法用foundation解释器，Mem0用external解释器。环境设置 `PYTHONPATH=src`、`HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`、`MEM0_TELEMETRY=False`、`LITELLM_LOCAL_MODEL_COST_MAP=True`，将FastEmbed缓存指向已核验资源；移除 `ANSWER_SYSTEM_EXTRA_INSTRUCTION`。

示意命令只创建一个全新RawDialogue prepare，所有路径及run名应明确对应独立复现身份：

```bash
PYTHONPATH=src /path/to/foundation/bin/python tools/run_unified_benchmarks.py \
  --benchmark memsyco --arm raw_dialogue \
  --selection data/manifests/unified-v8-v9-memsyco-subsets-20260928.json \
  --group development \
  --config data/diagnostics/unified-v8-v9-u2/native-common-config.json \
  --run u2-reproduction-memsyco-raw-dialogue \
  --runtime-root artifacts/u2-reproduction/memsyco-raw-dialogue \
  prepare --output artifacts/u2-reproduction/raw-prepared.json
```

其余参数相同，执行子命令为：

```text
run-history --history <prepared history_id> --prepared <receipt> --output <new build result>
run-job --job <prepared job_id> --prepared <receipt> --output <new task result>
```

MERIT只有完整arc的run-job，没有run-history。全部MERIT方法及MemSyco ordinary按需注入 `MILAI_LANGMEM_POSTGRES_DSN`；只从本机ignored私密配置读入环境，不在命令行、日志或Git中写值。每方法/arc独立Store、namespace、checkpoint、world、backend数据库，不能复用pilot或另一个方法的状态。

正式调用前冻结完整prepare、输入字节、方法/环境、真实model/tool契约、统计scorer、顺序、状态隔离和预算起点。原执行顺序：

| 单元 | benchmark / 方法 / 阶段 |
| --- | --- |
| 1—120 | MemSyco RawDialogue：60形成，60查询 |
| 121—240 | MemSyco StrongRawRAG：60形成，60查询 |
| 241—360 | MemSyco摘要：60形成，60查询 |
| 361—480 | MemSyco ordinary：60形成，60查询 |
| 481—600 | MemSyco Mem0：60形成，60查询 |
| 601—618 | MERIT FullHistory，18完整arcs |
| 619—636 | MERIT StrongRawRAG，18完整arcs |
| 637—654 | MERIT摘要，18完整arcs |
| 655—672 | MERIT ordinary，18完整arcs |
| 673—690 | MERIT Mem0，18完整arcs |

每次调用保存原命令、结果/trace哈希、全账本前后快照和时间。进程失败只停止待核查的串行范围；独立安全任务经Root核对后从下一个单元继续，不能自动重放已发生副作用的任务。原84/662/664/666保持失败；后三者的已完成episode和未运行后续不拼接。

## 评分与核账

所有Host工作终止后先冻结300个回答/状态，包括不存在完整回答的占位状态；只在此后加载EvaluationCase/gold。按[评分合同](../data/diagnostics/unified-v8-v9-u2/scoring-contract.json)顺序调用固定 `score_case`，每题最多一次Judge，Host不完整时0次。所有方法的同一输入使用原生rubric，保留原JSON schema/parse/aggregate；本地模型差异不称官方榜单复现。

MERIT沿用原world checker，成功需实际world满足且非pre_satisfied。保留episode/dependent/arc、host completion、maintenance completion及附加动作诊断。中断episode不凭最终world补造正常结果。

预注册cluster bootstrap：10000次、seed20260929、95%百分位、排序后(n−1)p线性插值。MemSyco按来源组在各任务内配对，MERIT按完整arc聚类。若配对端点有未评分项，保留计划分母和上下界，不输出CI，不删除缺失题。分层/统计不能据主表结果调参。

连续权威账本为原树 `artifacts/ser-v20/budget.json`。本次起止3713/5060988/37969 → 5941/10864712/414792，包含失败。原环境复现继续追加；别处独立复现另有明确账本身份，不能覆盖本实验或把历史费用清零。角色费用、actual HTTP输入/输出/embedding与ledger逐项相等；MCP/后端时延为overlapping inclusive值，物理I/O/GPU小时/货币费用unknown。

摘要capacity文件中的 `history_summary:<message>` 是一次尝试标志，不能与已包含摘要的公开消息生成计数相加。ordinary turn使用 `ordinary_records`，Mem0 backend使用 `backend_records`；字段不互相冒充。Mem0实际自动日期落定使用2026-09-28，其他日期复现可能改变形成文本，应单列真实请求而不静默固定成更有利日期。

公开制品仅包含元数据、配置、精简结果、方法和证据哈希；原始完整轨迹、gold原数据、私密DSN、数据库、环境、缓存和模型权重保持排除。新实验不能覆盖本报告，不因为这些复现步骤存在而自动启动。
