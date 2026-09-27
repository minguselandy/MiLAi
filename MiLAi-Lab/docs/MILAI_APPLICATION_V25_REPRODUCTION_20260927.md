# v25持久应用复现

运行源码固定在Git `44fb7ac9b6ed90cdfce1da8c17de734638d9b937`；后续结果提交不修改这批源码。使用独立checkout复现旧锁，不在当前工作树回退或覆盖既有运行。81文件mapping为`ff874dc00936261303336963a415007ddbe93bbdf06a87cb87ae0a7409ab6e38`，lock SHA为`796b32df3dbe5d5028d799bbdd92a7ff313ac17fd73ce34a84de3cae3d4d0e25`。

依赖由`uv.lock`固定，安装合同为`uv sync --frozen --group dev --group baseline-langmem`。本轮复用了现有环境，没有为结果发布再次安装、构建或调用模型。唯一构建和窄检查回执保存在[短执行冻结](../data/manifests/milai-application-v25-short-execution-freeze.json)；原始构建文件留在ignored artifacts。

## 环境

使用已有Host `http://127.0.0.1:7860/v1/`、`Qwen3.6-35B-A3B-FP8`，vLLM 0.27.1；embedding `http://127.0.0.1:7861/v1/`、`bge-m3`、1024维，vLLM 0.9.1。Host temperature=0、thinking=false、max_tokens=4096、context=65536、每公开消息最多12次生成。适配器发送JSON-action请求，不能为复现更改服务parser、thinking或容量来改善结果。完整固定合同在[配置](../configs/milai-application-v25.json)及[执行冻结](../data/manifests/milai-application-v25-short-execution-freeze.json)。

PostgreSQL使用独立研究库，支持上游PostgresStore的vector索引；DSN仅通过`MILAI_LANGMEM_POSTGRES_DSN`环境提供，不写进Git、命令参数或输出。配置中的tokenizer路径须指向与三个冻结文件SHA一致的本地目录，本机为`/cra/qwen36-35B`。公开配置锁固定当前端点与模型；第二模型需要独立适配/冻结，不能修改本锁并仍声称同一次实验。

## 单臂执行

以下命令从MiLAi-Lab目录执行，真实调用并发1。使用全新run ID、空namespace和独立runtime目录。例子创建独立复现账本；原实验的连续账本不能清零，旧结果也不能覆盖。先将环境DSN和tokenizer目录准备好。

```bash
export MILAI_REPRO_TOKENIZER=/cra/qwen36-35B
app_run=application-v25-reproduce-a4-$(date -u +%Y%m%dT%H%M%S)
app_dir="artifacts/$app_run"
mkdir -p "$app_dir"
export MILAI_REPRO_DIR="$app_dir"
.venv/bin/python - <<'PY'
import json, os
from pathlib import Path
config = json.loads(Path('configs/milai-application-v25.json').read_text())
config['capacity']['tokenizer_path'] = os.environ['MILAI_REPRO_TOKENIZER']
directory = Path(os.environ['MILAI_REPRO_DIR'])
config['budget_path'] = str(directory / 'budget.json')
(directory / 'config.json').write_text(json.dumps(config, indent=2) + '\n')
PY

app_args=(
  --config "$app_dir/config.json"
  --lock data/locks/milai-application-v25.lock.json
  --script data/diagnostics/milai-application-v25-script.json
  --input-freeze data/manifests/milai-application-v25-input-freeze.json
  --run "$app_run" --arm a4_selective_rebase
  --runtime-root "$app_dir/runtime"
)
.venv/bin/python tools/run_milai_application_v25.py prepare \
  "${app_args[@]}" --output "$app_dir/prepared.json"

for app_phase in 0 1 2 3 4; do
  .venv/bin/python tools/run_milai_application_v25.py run-phase \
    "${app_args[@]}" --prepared "$app_dir/prepared.json" \
    --phase "$app_phase" --stage "$app_run:phase-$app_phase" || break
done
```

prepare不调用模型，校验source/recipe/script/input freeze并绑定本地配置。每次run-phase是独立OS进程；同一臂五阶段必须使用同一run/config/runtime，按0→4执行。它们重开同一checkpoint、sidecar、业务库和Store。阶段内结果包括Host容量失败；进程exit0只说明运行器完成，不能当成任务通过。

短比较依次为`b1_control`、`a3_exact_refresh`、`a4_selective_rebase`、`a5_rank_bounded_rebase`，每臂独立目录和run ID；四臂全部输入相同。medium/long只比较B1/A4：将script和input-freeze文件名的`v25-`分别替换为`v25-medium-`、`v25-long-`，其余源锁和参数相同。所有长度输入在第一次短脚本真实请求前已固定，见[history inputs](../data/manifests/milai-application-v25-history-inputs.json)。

已知完成阶段再次调用读取保存结果，不重复执行；遇到未完成pending事件先保留和判断UNKNOWN，不自动重试跨Store/SQLite副作用。工具内部分提交后标签失败是预期世界行为，不回滚预留。容量失败仅隔离对应消息/同session后续依赖；其他服务、Store、instrumentation故障终止并保留产物。

## 评分与证据

[独立rubric](../data/diagnostics/milai-application-v25-rubric.json)只在运行后评分。每臂九条消息全部计分，分别核对实际参数、partial side effect、同ID恢复、原记忆ID更新、计划字段与实际状态是否均真实、两用户scope以及删除/保持。操作员的CRUD不算Host自主行为。Bob原记忆未维护完成状态是一项明确局限，不能由保持率遮盖。

原始证据在各runtime目录：`trace.jsonl`、`instrumentation.sqlite`、`checkpoints.sqlite`、`business-world.sqlite`、`business-journal.json`、`operator-memory.json`、`phase-progress.json`及五份phase结果。用真实Provider request/receipt ID连接request_material、revisions和assistant_lineage；get完成事件本身不等于正文送达。检查request copy与原checkpoint的差异是否仅为声明的projection/rebase，并保留原checkpoint全文。仅用当前Store最终值无法推断早先生成时看到了什么。

每阶段后Root用`PostgresStore(index=None).search(namespace, query=None)`读取两用户快照；这十次分析读取不进入模型、没有embedding，独立列出。方法exact get、observer额外读取、Host搜索、操作员写入和分析查询分别计费/计数。公开每臂manifest记录关键产物SHA、实际答案/工具摘要、业务状态和Store快照；原始Provider日志、私密配置和数据库不上传。

复现允许轨迹不同：本轮已有逐字段相同首请求却选择不同工具的证据，temperature=0也不能据此承诺相同ID、工具序列或分数。旧失败必须保留；任何修复都用新身份，不以最好复现替换原结果。
