# v26复现与交付

开发源码提交`2968f75ab69aedc0fd5349ba196aabe63da7f46f`；[执行冻结](../data/manifests/milai-external-memory-v26-execution-freeze.json)绑定两臂输入、配置、准备回执、source mapping和唯一build。冻结在首请求前完成，Git发布时间晚于B1开始。旧版本锁及费用不改写。结果见[报告](MILAI_EXTERNAL_MEMORY_V26_RESULTS_20260927.md)。

## 已执行验证

官方Mem0 SDK假Provider4项通过（原生infer=True、scope、批量embedding、BM25/entity、持久化重启、实际wire与预算），B1已有2项通过，受影响ruff/mypy、边界和CLI检查通过。标准旧环境因未装可选SDK跳过1项，隔离环境执行该项并通过。冻结后仅一次build，sdist SHA `e62d85918fd768717660f61a11debb543f34f561b16a1f65a5bf97896c498e1c`、wheel SHA `15e2896b20161d001bbd6fdcaeb767f643efda760d0662c0f6294792197a26d8`。无需为了阅读或发布文档重跑。

## 环境

以Lab为工作目录。两臂实际用Python3.12.11，旧研究环境为3.11且未修改。新增依赖锁在uv.lock，Mem0源码固定到`f8082a7345dadd9e042ebbc40b57b1498c8f6d63`，原LangMem仍固定`9d033b47d9ce53e37e92c92241b0496c0278932e`。安装时不要重新解析并覆盖现有锁：

```bash
UV_PROJECT_ENVIRONMENT=artifacts/external-memory-v26/.venv uv sync --locked --python 3.12.11 --group baseline-langmem --group external-mem0 --dev
uv pip install --python artifacts/external-memory-v26/.venv/bin/python https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl
```

本次实际由Luna先准备依赖、再准备NLP资产；无真实Host/embedding调用。spaCy版本3.8.16、fastembed0.8.1、qdrant-client1.19.1，全部固定版本和资产hash见[公开环境回执](../data/manifests/milai-external-memory-v26-environment-receipt.json)。该回执描述原环境，不是新机器安装成功证明。

BM25缓存路径为`artifacts/external-memory-v26/cache/fastembed`，Hub模型`Qdrant/bm25`固定revision `22b8d2af71a76161e18dd432d2cee0eefa66e412`。可在准备阶段用huggingface_hub的snapshot_download显式指定该revision和cache_dir下载；实际首次准备使用SparseTextEmbedding构造器下载，最终revision及18份原资产hash已记录。FastEmbed0.8.1的描述还要求mock.file、tamil.txt，而该快照缺失；仅这两个文件在本次隔离snapshot中补为空文件，hash均为`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`。不覆盖已有非空资源。准备完成后离线初始化BM25、加载en_core_web_sm并对照资产hash；运行期设置HF_HUB_OFFLINE，不能隐式重新下载或接受向量-only降级。

原环境回执的字节SHA为`8ceb0360a33ca40f4200bc0a1eb4173915419b8710b4a6db54959a1d063993d6`。公开副本与原ignored回执逐字节相同；冻结入口使用后者路径。重新建立环境时保留这份历史pin，并另存自己的实际环境检查记录，不能把复制历史pin当作验证通过。

```bash
mkdir -p artifacts/external-memory-v26
cp data/manifests/milai-external-memory-v26-environment-receipt.json artifacts/external-memory-v26/environment-receipt.json
```

生成服务仍为`http://127.0.0.1:7860/v1/`、Qwen3.6-35B-A3B-FP8；embedding为7861、bge-m3、1024维。温度0、max_tokens4096、thinking=false、公开消息max_calls12、context65536保持不变。tokenizer实际为`/cra/qwen36-35B`，文件hash在公开config；准备Postgres并通过`MILAI_LANGMEM_POSTGRES_DSN`环境变量提供凭据，避免写入公开文件。不要为了适配Mem0更改vLLM设置。

## 入口与隔离状态

公开CLI `tools/run_milai_external_memory_v26.py`提供prepare/run。prepare校验冻结身份与原四例/六session/六消息，不调用模型；run按臂建立普通LangMem或原生Mem0边界，复用原diagnostic循环。下面是新运行配置的示例，只在明确需要复现时执行；不要覆盖本次原始结果或重置既有连续费用。

```python
import copy
import json
import subprocess
import time
from pathlib import Path

lab = Path.cwd()
python = str(lab / 'artifacts/external-memory-v26/.venv/bin/python')
for arm in ('b1_control', 'mem0_native_autoadd'):
    run_id = f'external-v26-reproduce-{arm}-{time.time_ns()}'
    directory = Path('artifacts/external-memory-v26') / run_id
    directory.mkdir(parents=True, exist_ok=False)
    config = copy.deepcopy(json.loads(Path('configs/milai-external-memory-v26.json').read_text()))
    config['capacity']['tokenizer_path'] = '/cra/qwen36-35B'
    for key, filename in {
        'trace_path': 'trace.jsonl', 'checkpoint_path': 'checkpoints.sqlite',
        'business_journal_path': 'business-journal.json',
        'message_capacity_path': 'message-capacity.json',
        'sidecar_path': 'instrumentation.sqlite',
    }.items():
        config[key] = str(directory / filename)
    config_path = directory / 'config.json'
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n')
    options = ['--config', str(config_path), '--run', run_id, '--arm', arm]
    prepared = directory / 'prepared.json'
    subprocess.run([python, 'tools/run_milai_external_memory_v26.py', 'prepare',
                    *options, '--output', str(prepared)], check=True)
    subprocess.run([python, 'tools/run_milai_external_memory_v26.py', 'run',
                    *options, '--prepared', str(prepared), '--stage', run_id,
                    '--output', str(directory / 'run')], check=True)
```

此示例假定服务、资产、Postgres和历史pin都已按前述要求准备；两臂顺序执行，所有实际HTTP并发1。新run_id隔离用户记忆和Qdrant目录；同一budget_path累计计费。全新复现环境会建立自己的账本，它不等于本次历史累计值；本工作区已有账本不得删除、归零或替换。

不要仅凭进程exit code判语义通过：逐case检查`run/*/result.json`及`run/result.json`。原生SDK摄取journal位于`mem0_runtime_root/<run_id>/mem0-ingestion.json`；complete不重复摄取，pending视为结果未知，不自动重放。原始Provider trace、SQLite、Qdrant和环境缓存都在ignored artifacts，不提交Git。

## 评分与成本

保持[原rubric](../data/diagnostics/milai-lifecycle-v24-formation-rubric.json)不变，runtime不读取它。Root检查首次session持久记忆、实际业务调用/回执、later search是否真正进入HTTP和答案、两个临时控制是否无写入。原生摄取只接收实际user/final assistant；不得为了评分补写tool回执、gold或人工记忆。B1可自主manage/search；Mem0 Host只有绑定用户的native search，自动摄取每个完成轮次，连空结果与临时控制都必须计费。

将HTTP json_schema生成记为Host，json_object生成记为官方抽取；两者及全部embedding均与同一账本差额核对。不要把两臂不同工具/system合同当成首请求相同。已有正式结果为B1严格2/4、Mem0 4/4；新增26生成/59176tokens/669embeddingtokens，连续863/1042729/9617，exact reads107。新轨迹不保证逐字重现；不得替换或拼接历史最佳结果。

本轮完成一个外部系统切片。第二模型族尚无可用独立端点，标记NOT_RUN；广泛参数/密度扫描的主效果前提未成立。Product不迁移，master继续ACTIVE。
